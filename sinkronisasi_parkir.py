# Sinkronisasi Waktu pada Sistem Parkir Otomatis

from __future__ import annotations
import math
import heapq
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Any, Optional

# Konstanta (semuanya deterministik)
REQ_DELAY = 0.010  # waktu tempuh request (detik)
RESP_DELAY = 0.030  # waktu tempuh response (detik)
RTT = REQ_DELAY + RESP_DELAY  # 0.040 s
HALF_RTT = RTT / 2.0  # 0.020 s
SYNC_SCHEDULE = [0, 1800, 3600, 5400, 7200]  # detik waktu virtual

# Struktur data
@dataclass(frozen=True)
class Vehicle:
    vid: str
    entry_virtual: float
    exit_virtual: float

    @property
    def actual_duration(self) -> float:
        return self.exit_virtual - self.entry_virtual

@dataclass(order=True)
class Event:
    time: float
    tie: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False)

@dataclass
class SyncLog:
    gate: str
    request_virtual: float
    request_local: float
    server_recv_virtual: float
    server_timestamp: float
    response_virtual: float
    estimated_server_time: float
    actual_server_time_at_recv: float
    error: float
    before_correction: float
    after_correction: float

@dataclass
class TransactionResult:
    vehicle_id: str
    entry_local: float
    exit_local: float
    observed_duration: float
    tariff: int
    status: str  # "OK" atau "INVALID"
    expected_tariff: int
    expected_duration: float

@dataclass
class LamportRecord:
    virtual_time: float
    node: str
    direction: str  # SEND atau RECV
    message: str
    vehicle_id: Optional[str]
    lamport_ts: int

# Komponen inti simulasi
class VirtualClock:
    def __init__(self):
        self.now: float = 0.0
        self._last: float = 0.0

    def advance(self, to: float):
        if to < self.now - 1e-12:
            raise RuntimeError("Virtual time moved backwards")
        self._last = self.now
        self.now = to

    @property
    def last(self) -> float:
        return self._last

class ClockNode:
    def __init__(self, name: str, offset: float, drift: float):
        self.name = name
        self.offset = offset
        self.drift = drift  # detik per detik
        self.anchor_time: Optional[float] = None
        self.anchor_value: Optional[float] = None
        self.t0: float = 0.0

    def init_anchor(self, start_virtual: float):
        self.t0 = start_virtual
        self.anchor_time = None
        self.anchor_value = None

    def local_time(self, virtual_t: float) -> float:
        if self.anchor_time is None:
            return virtual_t + self.offset + self.drift * (virtual_t - self.t0)
        else:
            return self.anchor_value + (virtual_t - self.anchor_time) * (1.0 + self.drift)

    def sync(self, virtual_now: float, estimated_server_time: float) -> Tuple[float, float]:
        before = self.local_time(virtual_now)
        self.anchor_time = virtual_now
        self.anchor_value = estimated_server_time
        after = self.local_time(virtual_now)
        return before, after

class LamportClock:
    def __init__(self):
        self.counter = 0

    def tick(self) -> int:
        self.counter += 1
        return self.counter

    def send_event(self) -> int:
        return self.tick()

    def receive_event(self, remote_ts: int) -> int:
        self.counter = max(self.counter, remote_ts) + 1
        return self.counter

class CentralServer(ClockNode):
    def __init__(self):
        super().__init__("ServerPusat", offset=0.0, drift=0.0)
        self.entries: Dict[str, Tuple[float, int]] = {}
        self.lamport = LamportClock()

    def handle_entry(self, vid: str, entry_local: float, lamport_ts: int):
        self.entries[vid] = (entry_local, lamport_ts)

    def handle_exit(self, vid: str, exit_local: float, lamport_ts: int, tariff_fn) -> Tuple[float, int, str]:
        if vid not in self.entries:
            raise RuntimeError(f"Vehicle {vid} not found in entry records")
        entry_local, _ = self.entries[vid]
        duration = exit_local - entry_local
        tariff, status = tariff_fn(duration)
        return duration, tariff, status

# Fungsi helper
def calculate_tariff(duration_seconds: float) -> Tuple[int, str]:
    # Mengembalikan (tarif, status).
    if duration_seconds < 0:
        return 0, "INVALID"
    extra = max(0.0, duration_seconds - 3600.0)
    hours = math.ceil(extra / 3600.0)
    return 5000 + 3000 * hours, "OK"

# Penjadwal dan simulasi
class Simulator:
    def __init__(self, with_sync: bool, vehicles: List[Vehicle]):
        self.with_sync = with_sync
        self.vehicles = vehicles
        self.vc = VirtualClock()
        # Node
        self.gate_masuk = ClockNode("GateMasuk", offset=+240.0, drift=+0.001)
        self.gate_keluar = ClockNode("GateKeluar", offset=-300.0, drift=-0.0008)
        self.server = CentralServer()
        # Inisialisasi anchor
        self.gate_masuk.init_anchor(0.0)
        self.gate_keluar.init_anchor(0.0)
        self.server.init_anchor(0.0)
        # Clock Lamport per node
        self.lamport_masuk = LamportClock()
        self.lamport_keluar = LamportClock()
        self.lamport_server = self.server.lamport
        # Antrean event
        self.event_queue: List[Tuple[float, int, Event]] = []
        self._tie_counter = 0
        # Log
        self.sync_logs: List[SyncLog] = []
        self.transactions: List[TransactionResult] = []
        self.lamport_log: List[LamportRecord] = []
        self.clock_errors: List[float] = []
        self._pending_sync: Dict[str, Dict[str, float]] = {}
        self.observed_clock_errors: List[float] = []
        self._build_queue()

    def _push_event(self, time: float, kind: str, payload: Any):
        ev = Event(time, self._tie_counter, kind, payload)
        heapq.heappush(self.event_queue, (ev.time, ev.tie, ev))
        self._tie_counter += 1

    def _build_queue(self):
        for v in self.vehicles:
            self._push_event(v.entry_virtual, "VehicleEntry", v)
            self._push_event(v.exit_virtual, "VehicleExit", v)
        if self.with_sync:
            for sch in SYNC_SCHEDULE:
                self._push_event(sch, "CristianSyncRequest", "GateMasuk")
                self._push_event(sch, "CristianSyncRequest", "GateKeluar")
        # Response akan dijadwalkan secara dinamis.

    def run(self) -> Dict[str, Any]:
        while self.event_queue:
            _, _, ev = heapq.heappop(self.event_queue)
            self.vc.advance(ev.time)
            if ev.kind == "VehicleEntry":
                self._handle_vehicle_entry(ev.payload)
            elif ev.kind == "VehicleExit":
                self._handle_vehicle_exit(ev.payload)
            elif ev.kind == "CristianSyncRequest":
                self._handle_sync_request(ev.payload)
            elif ev.kind == "CristianSyncResponse":
                self._handle_sync_response(ev.payload)
            else:
                raise RuntimeError(f"Unknown event kind {ev.kind}")
        return {
            "sync_logs": self.sync_logs,
            "transactions": self.transactions,
            "lamport_log": self.lamport_log,
            "clock_errors": self.clock_errors,
            "max_observed_error": max(self.observed_clock_errors) if self.observed_clock_errors else 0.0,
        }

    # Pemrosesan kendaraan masuk
    def _handle_vehicle_entry(self, vehicle: Vehicle):
        vt = self.vc.now
        entry_local = self.gate_masuk.local_time(vt)
        # Catat error clock yang teramati untuk GateMasuk pada event ini
        self.observed_clock_errors.append(abs(entry_local - vt))
        ts_send = self.lamport_masuk.send_event()
        self.lamport_log.append(LamportRecord(vt, "GateMasuk", "SEND", "ENTRY", vehicle.vid, ts_send))
        ts_recv = self.lamport_server.receive_event(ts_send)
        self.lamport_log.append(LamportRecord(vt, "ServerPusat", "RECV", "ENTRY", vehicle.vid, ts_recv))
        self.server.handle_entry(vehicle.vid, entry_local, ts_recv)
        ts_ack = self.lamport_server.send_event()
        self.lamport_log.append(LamportRecord(vt, "ServerPusat", "SEND", "ACK_ENTRY", vehicle.vid, ts_ack))
        ts_ack_recv = self.lamport_masuk.receive_event(ts_ack)
        self.lamport_log.append(LamportRecord(vt, "GateMasuk", "RECV", "ACK_ENTRY", vehicle.vid, ts_ack_recv))

    # Pemrosesan kendaraan keluar
    def _handle_vehicle_exit(self, vehicle: Vehicle):
        vt = self.vc.now
        exit_local = self.gate_keluar.local_time(vt)
        # Catat error clock yang teramati untuk GateKeluar pada event ini
        self.observed_clock_errors.append(abs(exit_local - vt))
        # Minta catatan masuk
        ts_req = self.lamport_keluar.send_event()
        self.lamport_log.append(LamportRecord(vt, "GateKeluar", "SEND", "REQ_ENTRY", vehicle.vid, ts_req))
        ts_srv_recv = self.lamport_server.receive_event(ts_req)
        self.lamport_log.append(LamportRecord(vt, "ServerPusat", "RECV", "REQ_ENTRY", vehicle.vid, ts_srv_recv))
        # Response server dengan timestamp masuk
        ts_res = self.lamport_server.send_event()
        self.lamport_log.append(LamportRecord(vt, "ServerPusat", "SEND", "RESP_ENTRY", vehicle.vid, ts_res))
        ts_res_recv = self.lamport_keluar.receive_event(ts_res)
        self.lamport_log.append(LamportRecord(vt, "GateKeluar", "RECV", "RESP_ENTRY", vehicle.vid, ts_res_recv))
        entry_local, _ = self.server.entries[vehicle.vid]
        # Transaksi keluar
        ts_exit_tx = self.lamport_keluar.send_event()
        self.lamport_log.append(LamportRecord(vt, "GateKeluar", "SEND", "EXIT_TX", vehicle.vid, ts_exit_tx))
        ts_srv_exit = self.lamport_server.receive_event(ts_exit_tx)
        self.lamport_log.append(LamportRecord(vt, "ServerPusat", "RECV", "EXIT_TX", vehicle.vid, ts_srv_exit))
        duration, tariff, status = self.server.handle_exit(vehicle.vid, exit_local, ts_srv_exit, calculate_tariff)
        expected_tariff = self._expected_tariff(vehicle)
        self.transactions.append(
            TransactionResult(
                vehicle_id=vehicle.vid,
                entry_local=entry_local,
                exit_local=exit_local,
                observed_duration=duration,
                tariff=tariff,
                status=status,
                expected_tariff=expected_tariff,
                expected_duration=vehicle.actual_duration,
            )
        )

    def _expected_tariff(self, vehicle: Vehicle) -> int:
        tariff, _ = calculate_tariff(vehicle.actual_duration)
        return tariff

    # Penanganan sinkronisasi Cristian (request)
    def _handle_sync_request(self, gate_name: str):
        vt = self.vc.now
        gate = self.gate_masuk if gate_name == "GateMasuk" else self.gate_keluar
        request_local = gate.local_time(vt)
        server_recv_vt = vt + REQ_DELAY
        server_timestamp = server_recv_vt  # clock server sama dengan waktu virtual
        self._pending_sync[gate_name] = {
            "request_virtual": vt,
            "request_local": request_local,
            "server_timestamp": server_timestamp,
        }
        response_time = vt + RTT
        self._push_event(response_time, "CristianSyncResponse", gate_name)

    # Penanganan sinkronisasi Cristian (response)
    def _handle_sync_response(self, gate_name: str):
        vt = self.vc.now  # waktu request + RTT
        info = self._pending_sync.pop(gate_name)
        gate = self.gate_masuk if gate_name == "GateMasuk" else self.gate_keluar
        request_virtual = info["request_virtual"]
        request_local = info["request_local"]
        server_timestamp = info["server_timestamp"]
        server_recv_virtual = request_virtual + REQ_DELAY
        response_virtual = vt
        estimated_server = server_timestamp + HALF_RTT
        actual_server_at_recv = response_virtual
        error = estimated_server - actual_server_at_recv
        before_corr, after_corr = gate.sync(virtual_now=response_virtual, estimated_server_time=estimated_server)
        self.sync_logs.append(
            SyncLog(
                gate=gate_name,
                request_virtual=request_virtual,
                request_local=request_local,
                server_recv_virtual=server_recv_virtual,
                server_timestamp=server_timestamp,
                response_virtual=response_virtual,
                estimated_server_time=estimated_server,
                actual_server_time_at_recv=actual_server_at_recv,
                error=error,
                before_correction=before_corr,
                after_correction=after_corr,
            )
        )
        self.clock_errors.append(abs(error))

# Rangkaian self‑test
def run_self_tests(results_without: dict, results_with: dict) -> List[str]:
    msgs: List[str] = []
    # 1. Urutan log sinkronisasi
    def check_sync_log_order(logs: List[SyncLog]):
        prev_resp = -float('inf')
        for log in logs:
            assert log.response_virtual >= log.request_virtual - 1e-12, (
                f"Response before request for {log.gate} (req={log.request_virtual}, resp={log.response_virtual})"
            )
            assert log.response_virtual >= prev_resp - 1e-12, (
                f"Sync logs not chronological for {log.gate} (prev={prev_resp}, cur={log.response_virtual})"
            )
            prev_resp = log.response_virtual
    check_sync_log_order(results_without.get("sync_logs", []))
    check_sync_log_order(results_with.get("sync_logs", []))
    msgs.append("Urutan dan monotonisitas log sinkronisasi terverifikasi")
    # 2. Waktu sinkronisasi dan besaran error
    for log in results_with["sync_logs"]:
        expected_response = log.request_virtual + RTT
        assert math.isclose(log.response_virtual, expected_response, rel_tol=1e-12), (
            f"Sync response timing error for {log.gate}"
        )
        assert math.isclose(abs(log.error), 0.010, rel_tol=1e-9), f"Sync error magnitude not ~0.010 for {log.gate}"
    msgs.append("Waktu sinkronisasi dan besaran error terverifikasi")
    # 3. Log dari kedua gate
    gates = {log.gate for log in results_with["sync_logs"]}
    assert gates == {"GateMasuk", "GateKeluar"}, "Both gates must have sync logs"
    msgs.append("Log sinkronisasi independen untuk kedua gate tersedia")
    # 4. Pemeriksaan kausalitas Lamport dan jumlah pesan
    def validate_lamport(logs: List[LamportRecord], scenario_name: str):
        # Pengirim/penerima yang diproyeksikan untuk tiap tipe pesan
        expected_pair = {
            "ENTRY": ("GateMasuk", "ServerPusat"),
            "ACK_ENTRY": ("ServerPusat", "GateMasuk"),
            "REQ_ENTRY": ("GateKeluar", "ServerPusat"),
            "RESP_ENTRY": ("ServerPusat", "GateKeluar"),
            "EXIT_TX": ("GateKeluar", "ServerPusat"),
        }
        last_counter: Dict[str, int] = {"GateMasuk": 0, "GateKeluar": 0, "ServerPusat": 0}
        send_info: Dict[Tuple[str, Optional[str]], Tuple[int, float]] = {}
        send_counts: Dict[str, int] = {}
        recv_seen: set = set()
        send_seen: set = set()
        for rec in logs:
            if rec.direction == "SEND":
                # node harus sesuai dengan pengirim yang diharapkan
                expected_sender, _ = expected_pair[rec.message]
                assert rec.node == expected_sender, f"SEND of {rec.message} from wrong node {rec.node} (expected {expected_sender}) in {scenario_name}"
                key = (rec.message, rec.vehicle_id)
                assert key not in send_seen, f"Duplicate SEND for {rec.message} vehicle {rec.vehicle_id} in {scenario_name}"
                send_seen.add(key)
                send_counts[rec.message] = send_counts.get(rec.message, 0) + 1
                send_info[key] = (rec.lamport_ts, rec.virtual_time)
                last_counter[rec.node] = rec.lamport_ts
            else:  # RECV
                # node harus sesuai dengan penerima yang diproyeksikan
                _, expected_receiver = expected_pair[rec.message]
                assert rec.node == expected_receiver, f"RECV of {rec.message} at wrong node {rec.node} (expected {expected_receiver}) in {scenario_name}"
                key = (rec.message, rec.vehicle_id)
                assert key not in recv_seen, f"Duplicate RECV for {rec.message} vehicle {rec.vehicle_id} in {scenario_name}"
                recv_seen.add(key)
                assert key in send_info, f"No matching SEND for RECV {rec} in {scenario_name}"
                send_ts, send_vt = send_info[key]
                # Urutan waktu virtual
                assert rec.virtual_time >= send_vt - 1e-12, f"Virtual time regression for {rec} in {scenario_name}"
                # Aturan Lamport
                expected_counter = max(last_counter[rec.node], send_ts) + 1
                assert rec.lamport_ts == expected_counter, (
                    f"Lamport rule violation at {rec} (expected {expected_counter}) in {scenario_name}"
                )
                last_counter[rec.node] = rec.lamport_ts
        # Pastikan setiap tipe pesan dikirim tepat 4 kali (satu per kendaraan)
        expected_msgs = {"ENTRY", "ACK_ENTRY", "REQ_ENTRY", "RESP_ENTRY", "EXIT_TX"}
        for mtype in expected_msgs:
            cnt = send_counts.get(mtype, 0)
            assert cnt == 4, f"Message {mtype} SEND occurs {cnt} times in {scenario_name}, expected 4"
        # Pastikan jumlah total SEND dan RECV masing-masing sesuai ekspektasi 20
        assert len(send_seen) == 20, f"Total SEND records {len(send_seen)} in {scenario_name}, expected 20"
        assert len(recv_seen) == 20, f"Total RECV records {len(recv_seen)} in {scenario_name}, expected 20"
        # Panjang total log seharusnya 40
        assert len(logs) == 40, f"Lamport log length {len(logs)} in {scenario_name}, expected 40"
    validate_lamport(results_without["lamport_log"], "without sync")
    validate_lamport(results_with["lamport_log"], "with sync")
    msgs.append("Kausalitas Lamport dan jumlah pesan tervalidasi untuk kedua skenario")
    # 5. Kebenaran tarif
    def tariff_check(res_list: List[TransactionResult], expect_all_correct: bool):
        correct = sum(1 for tr in res_list if tr.status == "OK" and tr.tariff == tr.expected_tariff)
        if expect_all_correct:
            assert correct == 4, f"Expected 4 correct tariffs, got {correct}"
        else:
            assert correct == 1, f"Expected exactly 1 correct tariff without sync, got {correct}"
    tariff_check(results_without["transactions"], expect_all_correct=False)
    tariff_check(results_with["transactions"], expect_all_correct=True)
    msgs.append("Hasil tarif sesuai kriteria penerimaan")
    # 6. Durasi negatif Kendaraan A
    veh_a = next(tr for tr in results_without["transactions"] if tr.vehicle_id == "A")
    assert veh_a.observed_duration < 0, "Vehicle A should have negative duration without sync"
    assert math.isclose(veh_a.observed_duration, -240.348, rel_tol=1e-3), f"Vehicle A duration mismatch: {veh_a.observed_duration}"
    msgs.append("Durasi negatif Kendaraan A terverifikasi (≈ -240.348 s)")
    return msgs

# Fungsi helper pelaporan
def print_header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80 + "\n")

def print_config(gate_masuk: ClockNode, gate_keluar: ClockNode):
    print("Konfigurasi Awal Nodes:")
    print(f"  {gate_masuk.name}: offset={gate_masuk.offset}s, drift={gate_masuk.drift}s/s")
    print(f"  {gate_keluar.name}: offset={gate_keluar.offset}s, drift={gate_keluar.drift}s/s")
    print("  ServerPusat: offset=0s, drift=0s/s (reference)\n")

def print_transaction_table(results: List[TransactionResult]):
    print("| Kendaraan | Waktu Masuk Lokal | Waktu Keluar Lokal | Durasi Terbaca (s) | Tarif | Status | Expected Tarif |")
    print("|-----------|-------------------|--------------------|--------------------|-------|--------|----------------|")
    for tr in results:
        dur = f"{tr.observed_duration:.3f}"
        print(f"| {tr.vehicle_id:8} | {tr.entry_local:17.3f} | {tr.exit_local:18.3f} | {dur:>18} | Rp{tr.tariff:,} | {tr.status:6} | Rp{tr.expected_tariff:,} |")
    print()

def print_sync_logs(logs: List[SyncLog]):
    if not logs:
        print("Tidak ada sinkronisasi yang dijalankan.")
        return
    for log in logs:
        print(f"--- Sinkronisasi {log.gate} ---")
        print(f"Waktu request (virtual): {log.request_virtual:.3f}s")
        print(f"   Local request clock : {log.request_local:.6f}s")
        print(f"Server menerima request (virtual) : {log.server_recv_virtual:.3f}s")
        print(f"   Server timestamp    : {log.server_timestamp:.6f}s")
        print(f"Waktu response (virtual) : {log.response_virtual:.3f}s")
        print(f"   Estimasi server time: {log.estimated_server_time:.6f}s")
        print(f"   Server waktu nyata   : {log.actual_server_time_at_recv:.6f}s")
        print(f"   Error (estimasi‑nyata): {log.error:+.6f}s")
        print(f"   Clock sebelum koreksi: {log.before_correction:.6f}s")
        print(f"   Clock sesudah koreksi: {log.after_correction:.6f}s\n")

def print_lamport_log(logs: List[LamportRecord]):
    print("Log Lamport (chronological):")
    print("| Virtual(s) | Node        | Dir  | Message       | Vehicle | Lamport |")
    print("|------------|-------------|------|---------------|---------|---------|")
    for rec in logs:
        print(f"| {rec.virtual_time:10.3f} | {rec.node:11} | {rec.direction:4} | {rec.message:13} | {rec.vehicle_id or '-':7} | {rec.lamport_ts:7} |")
    print()

def print_comparison(results_without: dict, results_with: dict):
    correct_no = sum(1 for tr in results_without["transactions"] if tr.status == "OK" and tr.tariff == tr.expected_tariff)
    correct_yes = sum(1 for tr in results_with["transactions"] if tr.status == "OK" and tr.tariff == tr.expected_tariff)
    neg_no = sum(1 for tr in results_without["transactions"] if tr.status == "INVALID")
    neg_yes = sum(1 for tr in results_with["transactions"] if tr.status == "INVALID")
    total_vehicles = len(results_without["transactions"])
    sync_rounds = len(results_with["sync_logs"])  # jumlah event response (seharusnya 10)
    immediate_sync_error = max(results_with.get("clock_errors", [0])) if results_with.get("clock_errors") else 0.0
    max_observed_error = results_with.get("max_observed_error", 0.0)
    print("| Metric                     | Tanpa Sync | Dengan Cristian |")
    print("|----------------------------|------------|-----------------|")
    print(f"| Correct tariffs            | {correct_no}/4      | {correct_yes}/4         |")
    print(f"| Incorrect tariffs          | {4-correct_no}/4      | {4-correct_yes}/4         |")
    print(f"| Negative durations         | {neg_no}          | {neg_yes}           |")
    print(f"| Sinkronisasi aktif          | Tidak      | Ya               |")
    print(f"| Total vehicles processed    | {total_vehicles}          | {total_vehicles}               |")
    print(f"| Total sync response events | 0          | {sync_rounds}               |")
    print(f"| Sync rounds per gate       | 0          | {len(SYNC_SCHEDULE)}         |")
    print(f"| Immediate sync error (s)   | -          | {immediate_sync_error:.6f} |")
    print(f"| Max observed clock error (s) | -          | {max_observed_error:.6f} |")
    print()

def main():
    vehicles = [
        Vehicle("A", entry_virtual=60.0, exit_virtual=360.0),   # 5 menit
        Vehicle("B", entry_virtual=120.0, exit_virtual=4020.0), # 65 menit
        Vehicle("C", entry_virtual=180.0, exit_virtual=7680.0), # 125 menit
        Vehicle("D", entry_virtual=240.0, exit_virtual=5640.0), # 90 menit
    ]
    # Skenario 1: tanpa sinkronisasi
    sim_no = Simulator(with_sync=False, vehicles=vehicles)
    result_no = sim_no.run()
    # Skenario 2: dengan sinkronisasi
    sim_yes = Simulator(with_sync=True, vehicles=vehicles)
    result_yes = sim_yes.run()
    # Pelaporan
    print_header("SIMULASI PARKIR – Scenario 1 (Tanpa Sinkronisasi)")
    print_config(sim_no.gate_masuk, sim_no.gate_keluar)
    print_transaction_table(result_no["transactions"])
    print_lamport_log(result_no["lamport_log"])
    print_header("SIMULASI PARKIR – Scenario 2 (Dengan Cristian Sync)")
    print_config(sim_yes.gate_masuk, sim_yes.gate_keluar)
    print_sync_logs(result_yes["sync_logs"])
    print_transaction_table(result_yes["transactions"])
    print_lamport_log(result_yes["lamport_log"])
    print_header("Perbandingan Kedua Scenario")
    print_comparison(result_no, result_yes)
    print_header("Hasil Rangkaian Self-test")
    msgs = run_self_tests(result_no, result_yes)
    for m in msgs:
        print(m)

if __name__ == "__main__":
    main()