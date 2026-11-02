# Sinkronisasi Waktu pada Sistem Parkir Otomatis

## Deskripsi
Implementasi simulasi akademik yang memperlihatkan tiga node (Gate Masuk, Gate Keluar, Server Pusat) dengan model jam fisik (offset & drift), algoritma Cristian untuk sinkronisasi jam, serta Lamport Logical Clock untuk urutan pesan transaksi parkir. Dua skenario disimulasi:

1. **Tanpa Sinkronisasi** – hanya transaksi parkir.
2. **Dengan Sinkronisasi Cristian** – menambahkan event sinkronisasi pada waktu virtual 0, 1800, 3600, 5400, dan 7200 detik.

Semua perhitungan dijalankan deterministik pada *virtual time* tanpa `time.sleep()`.

## Cara Menjalankan
```bash
python sinkronisasi_parkir.py
```
Script akan menampilkan laporan lengkap untuk kedua skenario, perbandingan metrik, dan hasil self‑test suite.

## Contoh Output
```
================================================================================
SIMULASI PARKIR – Scenario 1 (Tanpa Sinkronisasi)
================================================================================

Konfigurasi Awal Nodes:
  GateMasuk: offset=240.0s, drift=0.001s/s
  GateKeluar: offset=-300.0s, drift=-0.0008s/s
  ServerPusat: offset=0s, drift=0s/s (reference)

| Kendaraan | Waktu Masuk Lokal | Waktu Keluar Lokal | Durasi Terbaca (s) | Tarif | Status | Expected Tarif |
|-----------|-------------------|--------------------|--------------------|-------|--------|----------------|
| A        |           300.060 |             59.712 |           -240.348 | Rp0 | INVALID | Rp5,000 |
| B        |           360.120 |           3716.784 |           3356.664 | Rp5,000 | OK     | Rp8,000 |
| D        |           480.240 |           5335.488 |           4855.248 | Rp8,000 | OK     | Rp8,000 |
| C        |           420.180 |           7373.856 |           6953.676 | Rp8,000 | OK     | Rp11,000 |

Log Lamport (chronological):
| Virtual(s) | Node        | Dir  | Message       | Vehicle | Lamport |
|------------|-------------|------|---------------|---------|---------|
|     60.000 | GateMasuk   | SEND | ENTRY         | A       |       1 |
|     60.000 | ServerPusat | RECV | ENTRY         | A       |       2 |
|     60.000 | ServerPusat | SEND | ACK_ENTRY     | A       |       3 |
|     60.000 | GateMasuk   | RECV | ACK_ENTRY     | A       |       4 |
... (remaining Lamport records omitted for brevity) ...

================================================================================
SIMULASI PARKIR – Scenario 2 (Dengan Cristian Sync)
================================================================================

Konfigurasi Awal Nodes:
  GateMasuk: offset=240.0s, drift=0.001s/s
  GateKeluar: offset=-300.0s, drift=-0.0008s/s
  ServerPusat: offset=0s, drift=0s/s (reference)

--- Sinkronisasi GateMasuk ---
Waktu request (virtual): 0.000s
   Local request clock : 240.000000s
Server menerima request (virtual) : 0.010s
   Server timestamp    : 0.010000s
Waktu response (virtual): 0.040s
   Estimasi server time: 0.030000s
   Server waktu nyata   : 0.040000s
   Error (estimasi‑nyata): -0.010000s
   Clock sebelum koreksi: 240.040040s
   Clock sesudah koreksi: 240.030040s
... (sinkronisasi GateKeluar and further logs omitted) ...

| Kendaraan | Waktu Masuk Lokal | Waktu Keluar Lokal | Durasi Terbaca (s) | Tarif | Status | Expected Tarif |
|-----------|-------------------|--------------------|--------------------|-------|--------|----------------|
| A        |            60.050 |            359.702 |            299.652 | Rp5,000 | OK     | Rp5,000 |
| B        |           120.110 |           4019.654 |           3899.544 | Rp8,000 | OK     | Rp8,000 |
| D        |           240.230 |           5639.798 |           5399.568 | Rp8,000 | OK     | Rp8,000 |
| C        |           180.170 |           7679.606 |           7499.436 | Rp11,000 | OK     | Rp11,000 |

Log Lamport (chronological):
| Virtual(s) | Node        | Dir  | Message       | Vehicle | Lamport |
|------------|-------------|------|---------------|---------|---------|
|     60.000 | GateMasuk   | SEND | ENTRY         | A       |       1 |
|     60.000 | ServerPusat | RECV | ENTRY         | A       |       2 |
|     60.000 | ServerPusat | SEND | ACK_ENTRY     | A       |       3 |
|     60.000 | GateMasuk   | RECV | ACK_ENTRY     | A       |       4 |
... (remaining Lamport records omitted) ...

================================================================================
Perbandingan Kedua Scenario
================================================================================

| Metric                     | Tanpa Sync | Dengan Cristian |
|----------------------------|------------|-----------------|
| Correct tariffs            | 1/4      | 4/4         |
| Incorrect tariffs          | 3/4      | 0/4         |
| Negative durations         | 1          | 0           |
| Sinkronisasi aktif          | Tidak      | Ya               |
| Total vehicles processed    | 4          | 4               |
| Cristian sync rounds       | 0          | 10               |
| Immediate sync error (s)   | -          | 0.010000 |
| Max observed clock error (s) | -          | 0.393968 |

================================================================================
Self‑test Suite Results
================================================================================

✔ Sync log ordering and monotonicity verified
✔ Sync timing and error magnitude verified
✔ Independent gate sync logs present
✔ Lamport causality and message count validated for both scenarios
✔ Tariff outcomes match acceptance criteria
✔ Vehicle A negative duration verified (≈ -240.348 s)
```

## Catatan Implementasi
- **Maximum observed clock error** dihitung dari selisih mutlak `|gate.local_time(vt) - vt|` pada setiap event kendaraan.
- **Immediate sync error** tetap ~0.010 s (selisih estimasi vs. real server time).
- **Lamport validation** kini memastikan setiap pesan SEND memiliki RECV pasangan, pengirim/penerima sesuai jenis pesan, dan hitungan tepat 4 per tipe pesan (total 20 pertukaran, 40 rekaman).
- Semua nilai dihitung secara dinamis; tidak ada hard‑coded angka.

Jika ada pertanyaan atau perubahan lebih lanjut, silakan beri tahu.
