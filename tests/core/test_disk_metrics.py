"""Tests for local disk throughput sampling helpers."""

from __future__ import annotations

import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.service.app import (
    LocalDiskIoSample,
    collect_local_disk_io_sample,
    _read_linux_block_device_io_sample,
    _read_posix_process_io_sample,
    calculate_local_disk_metrics,
)


class LocalDiskMetricsTests(unittest.TestCase):
    def test_disk_metrics_calculate_rate_from_samples(self) -> None:
        previous = LocalDiskIoSample(timestamp=10.0, read_bytes=1000, write_bytes=500)
        current = LocalDiskIoSample(timestamp=12.0, read_bytes=1800, write_bytes=900)

        metrics = calculate_local_disk_metrics(previous, current)

        self.assertEqual(metrics["disk_read_bps"], 400)
        self.assertEqual(metrics["disk_write_bps"], 200)
        self.assertEqual(metrics["disk_total_bps"], 600)
        self.assertEqual(metrics["disk_activity_bps"], 600)

    def test_disk_metrics_clamp_negative_or_missing_samples(self) -> None:
        sample = LocalDiskIoSample(timestamp=10.0, read_bytes=1000, write_bytes=500)

        self.assertEqual(
            calculate_local_disk_metrics(None, sample),
            {
                "disk_read_bps": 0,
                "disk_write_bps": 0,
                "disk_total_bps": 0,
                "disk_activity_bps": 0,
            },
        )

    @unittest.skipIf(os.name == "nt", "Linux /sys mount metrics")
    def test_linux_library_disk_sample_reads_block_device_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mountinfo = root / "mountinfo"
            sys_dev_block_root = root / "sys" / "dev" / "block"
            stat_path = sys_dev_block_root / "8:1" / "stat"
            stat_path.parent.mkdir(parents=True, exist_ok=True)
            mountinfo.write_text(
                "\n".join(
                    [
                        "42 34 8:1 / /media/library rw,relatime - ext4 /dev/sda1 rw",
                        "43 42 8:1 /sub /media/library/subdir rw,relatime - ext4 /dev/sda1 rw",
                    ]
                ),
                encoding="utf-8",
            )
            stat_path.write_text("1 0 2 0 3 0 4 0 0 0 0", encoding="utf-8")

            sample = _read_linux_block_device_io_sample(
                "/media/library/subdir",
                mountinfo_path=mountinfo,
                sys_dev_block_root=sys_dev_block_root,
            )

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.read_bytes, 2 * 512)
        self.assertEqual(sample.write_bytes, 4 * 512)
        self.assertEqual(
            calculate_local_disk_metrics(sample, None),
            {
                "disk_read_bps": 0,
                "disk_write_bps": 0,
                "disk_total_bps": 0,
                "disk_activity_bps": 0,
            },
            )
        self.assertEqual(
            calculate_local_disk_metrics(
                LocalDiskIoSample(
                    timestamp=sample.timestamp + 1.0,
                    read_bytes=2000,
                    write_bytes=1000,
                ),
                sample,
            ),
            {
                "disk_read_bps": 0,
                "disk_write_bps": 0,
                "disk_total_bps": 0,
                "disk_activity_bps": 0,
                },
            )

    @unittest.skipIf(os.name == "nt", "Linux block-device metrics")
    def test_linux_disk_sample_prefers_library_disk_over_process_io(self) -> None:
        library_sample = LocalDiskIoSample(
            timestamp=20.0,
            read_bytes=4096,
            write_bytes=2048,
        )
        process_sample = LocalDiskIoSample(
            timestamp=21.0,
            read_bytes=8192,
            write_bytes=4096,
        )

        with patch(
            "src.core.service.app._read_linux_block_device_io_sample",
            return_value=library_sample,
        ) as library_patch, patch(
            "src.core.service.app._read_posix_process_io_sample",
            return_value=process_sample,
        ) as process_patch:
            sample = collect_local_disk_io_sample(
                "/media/library",
                process_pid=1234,
            )

        self.assertEqual(sample, library_sample)
        library_patch.assert_called_once_with("/media/library")
        process_patch.assert_not_called()

    def test_posix_process_io_sample_reads_proc_io_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = Path(tmp)
            io_path = proc_root / "1234" / "io"
            io_path.parent.mkdir(parents=True, exist_ok=True)
            io_path.write_text(
                "\n".join(
                    [
                        "rchar: 123",
                        "wchar: 456",
                        "syscr: 7",
                        "syscw: 8",
                        "read_bytes: 1111",
                        "write_bytes: 2222",
                    ]
                ),
                encoding="utf-8",
            )

            sample = _read_posix_process_io_sample(1234, proc_root=proc_root)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.read_bytes, 1111)
        self.assertEqual(sample.write_bytes, 2222)


if __name__ == "__main__":
    unittest.main()
