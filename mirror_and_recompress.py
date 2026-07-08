#!/usr/bin/env python3

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from enum import Enum
from typing import BinaryIO, Callable, Iterator, Optional


SCRIPT_PATH = os.path.realpath(__file__)
SCRIPT_NAME = os.path.basename(sys.argv[0])
CHUNK_SIZE = 1024 * 1024


@dataclasses.dataclass(frozen=True)
class Codec:
    name: str
    suffix: str
    detect_suffixes: tuple[str, ...]
    compressor_binary: str
    decompressor_binary: str
    compressor_args: Optional[Callable[[list[str]], list[str]]]
    decompressor_args: Optional[Callable[[str], list[str]]]

    def compress_command(self, opts: list[str]) -> list[str]:
        if self.compressor_args is None:
            raise ValueError(f"{self.name} has no compressor command")
        return self.compressor_args(opts)

    def decompress_command(self, path: str) -> list[str]:
        if self.decompressor_args is None:
            raise ValueError(f"{self.name} has no decompressor command")
        return self.decompressor_args(path)


def codec(
    name: str,
    suffix: str,
    detect_suffixes: tuple[str, ...],
    compressor_binary: str,
    decompressor_binary: str,
    compressor_args: Optional[Callable[[list[str]], list[str]]],
    decompressor_args: Optional[Callable[[str], list[str]]],
) -> Codec:
    return Codec(
        name=name,
        suffix=suffix,
        detect_suffixes=detect_suffixes,
        compressor_binary=compressor_binary,
        decompressor_binary=decompressor_binary,
        compressor_args=compressor_args,
        decompressor_args=decompressor_args,
    )


CODECS: dict[str, Codec] = {
    "none": codec("none", "", (), "cat", "cat", None, None),
    "gzip": codec("gzip", ".gz", (".tar.gz", ".tgz", ".gz"), "gzip", "gzip", lambda opts: ["gzip", *opts, "-c"], lambda path: ["gzip", "-d", "-c", "--", path]),
    "bzip2": codec("bzip2", ".bz2", (".tar.bz2", ".tbz2", ".bz2"), "bzip2", "bzip2", lambda opts: ["bzip2", *opts, "-c"], lambda path: ["bzip2", "-d", "-c", "--", path]),
    "xz": codec("xz", ".xz", (".tar.xz", ".txz", ".xz"), "xz", "xz", lambda opts: ["xz", *opts, "-c"], lambda path: ["xz", "-d", "-c", "--", path]),
    "lzma": codec("lzma", ".lzma", (".lzma",), "xz", "xz", lambda opts: ["xz", "--format=lzma", *opts, "-c"], lambda path: ["xz", "--format=lzma", "-d", "-c", "--", path]),
    "lz4": codec("lz4", ".lz4", (".lz4",), "lz4", "lz4", lambda opts: ["lz4", "-q", *opts, "-c"], lambda path: ["lz4", "-q", "-d", "-c", "--", path]),
    "zstd": codec("zstd", ".zst", (".tar.zst", ".tzst", ".zst", ".zstd"), "zstd", "zstd", lambda opts: ["zstd", "-q", *opts, "-c"], lambda path: ["zstd", "-q", "-d", "-c", "--", path]),
    "brotli": codec("brotli", ".br", (".br",), "brotli", "brotli", lambda opts: ["brotli", *opts, "-c"], lambda path: ["brotli", "-d", "-c", "--", path]),
    "lzip": codec("lzip", ".lz", (".lz",), "lzip", "lzip", lambda opts: ["lzip", *opts, "-c"], lambda path: ["lzip", "-d", "-c", "--", path]),
    "compress": codec("compress", ".Z", (".Z",), "compress", "gzip", lambda opts: ["compress", *opts, "-c"], lambda path: ["gzip", "-d", "-c", "--", path]),
}


DETECTION_SUFFIXES = sorted(
    ((suffix, name) for name, codec_obj in CODECS.items() for suffix in codec_obj.detect_suffixes),
    key=lambda item: len(item[0]),
    reverse=True,
)
STRIP_SUFFIX_REPLACEMENTS = {
    ".tar.gz": ".tar",
    ".tgz": ".tar",
    ".tar.bz2": ".tar",
    ".tbz2": ".tar",
    ".tar.xz": ".tar",
    ".txz": ".tar",
    ".tar.zst": ".tar",
    ".tzst": ".tar",
}
STRIP_SUFFIXES = sorted(
    [suffix for suffix in STRIP_SUFFIX_REPLACEMENTS] + [codec_obj.suffix for codec_obj in CODECS.values() if codec_obj.suffix] + [".zstd"],
    key=len,
    reverse=True,
)
STAT_ORDER = ("converted", "verified", "retained", "deleted", "total")


class OutcomeAction(str, Enum):
    CONVERTED = "converted"
    VERIFIED = "verified"
    RETAINED = "retained"
    DELETED = "deleted"


class WorkAction(str, Enum):
    VERIFY_METADATA = "verify_metadata"
    VERIFY_BYTES = "verify_bytes"
    CONVERT = "convert"
    RETAIN = "retain"
    DELETE = "delete"


@dataclasses.dataclass(frozen=True)
class Config:
    source_dir: str
    target_dir: str
    compressor: str
    compress_opts: list[str]
    target_suffix: str
    hosts_file: str
    jobs: Optional[int]
    delete_extra: bool
    compare_bytes: bool
    dry_run: bool
    verbose: bool
    quiet: bool


@dataclasses.dataclass(frozen=True)
class ConfigValues:
    source_dir: str
    target_dir: str
    compressor: str
    compress_opts: list[str]
    target_suffix: str
    hosts_file: str
    jobs: Optional[int]
    delete_extra: bool
    compare_bytes: bool
    dry_run: bool
    verbose: bool
    quiet: bool


@dataclasses.dataclass(frozen=True)
class FileTask:
    source_path: str
    source_rel: str
    input_format: str
    target_rel: str
    target_path: str
    input_size: int
    source_mtime_ns: int


@dataclasses.dataclass(frozen=True)
class TargetSnapshot:
    rel_path: str
    path: str
    size: int
    mode: int
    mtime_ns: int


@dataclasses.dataclass(frozen=True)
class WorkItem:
    action: WorkAction
    reason: str
    task: Optional[FileTask] = None
    target: Optional[TargetSnapshot] = None


@dataclasses.dataclass(frozen=True)
class TaskOutcome:
    action: OutcomeAction
    source_rel: str = ""
    target_rel: str = ""
    reason: str = ""
    input_format: str = ""
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    uncompressed_size: Optional[int] = None


@dataclasses.dataclass
class StatsBucket:
    files: int = 0
    uncompressed: int = 0
    input_bytes: int = 0
    output_bytes: int = 0
    uncompressed_known: bool = True
    input_known: bool = True
    output_known: bool = True

    def add(self, outcome: TaskOutcome) -> None:
        self.files += 1
        self._add_metric("uncompressed", outcome.uncompressed_size)
        self._add_metric("input_bytes", outcome.input_size)
        self._add_metric("output_bytes", outcome.output_size)

    def _add_metric(self, attr: str, value: Optional[int]) -> None:
        known_attr = {
            "uncompressed": "uncompressed_known",
            "input_bytes": "input_known",
            "output_bytes": "output_known",
        }[attr]
        if value is None:
            setattr(self, known_attr, False)
            return
        setattr(self, attr, getattr(self, attr) + value)


class StatsAccumulator:
    def __init__(self) -> None:
        self.buckets = {status: StatsBucket() for status in STAT_ORDER}

    def add(self, outcome: TaskOutcome) -> None:
        self.buckets[outcome.action.value].add(outcome)

    def compute_total(self) -> None:
        total = StatsBucket()
        for status in ("converted", "verified", "retained"):
            bucket = self.buckets[status]
            total.files += bucket.files
            total.uncompressed += bucket.uncompressed
            total.output_bytes += bucket.output_bytes
            total.uncompressed_known &= bucket.uncompressed_known
            total.output_known &= bucket.output_known
        for status in ("converted", "verified"):
            bucket = self.buckets[status]
            total.input_bytes += bucket.input_bytes
            total.input_known &= bucket.input_known
        self.buckets["total"] = total

    def summary_rows(self, config: Config) -> list[tuple[str, StatsBucket, bool]]:
        self.compute_total()
        rows: list[tuple[str, StatsBucket, bool]] = [
            ("converted", self.buckets["converted"], True),
            ("verified", self.buckets["verified"], True),
        ]
        if not config.delete_extra:
            rows.append(("retained", self.buckets["retained"], False))
        rows.append(("total", self.buckets["total"], True))
        if config.delete_extra:
            rows.append(("deleted", self.buckets["deleted"], False))
        return rows


def status_label(status: str, config: Config, *, lowercase: bool = False) -> str:
    label = {
        "converted": "Would convert" if config.dry_run else "Converted",
        "verified": "Verified" if config.compare_bytes else "Checked",
        "retained": "Retained",
        "deleted": "Would delete" if config.dry_run else "Deleted",
        "total": "Total",
    }[status]
    return label.lower() if lowercase else label


def usage_text() -> str:
    return f"""Usage: {SCRIPT_NAME} [options] <source_dir> <target_dir>

Mirror a directory tree into another directory while recompressing each regular
file into the selected output format. Known compressed inputs are decompressed
first, then recompressed into the target format.

Options:
  --compressor NAME       Target compressor: none, gzip, bzip2, xz, lzma, lz4,
                          zstd, brotli, lzip, compress
  --compress-opts OPTS    Extra options passed to the target compressor
                          Example: --compress-opts "-19 -T0"
  --suffix SUFFIX         Override the target filename suffix
  --hosts-file PATH       GNU parallel sshlogin file; when set, conversions run
                          remotely through GNU parallel
  --jobs N                Parallel job count; local runs default to the number
                          of processors, remote runs use GNU parallel
  --delete                Delete files in the target tree that are not
                          produced by this run
  --compare-bytes         Before reusing a target, compare the uncompressed
                          data streams byte-for-byte
  --verbose, -v           Show planning, verification, and cleanup details
  --dry-run               Show planned work without writing changes
  --quiet                 Reduce progress output
  --list-compressors      List supported compressors available on this system
  -h, --help              Show this help
"""


def human_size(value: Optional[int], known: bool = True) -> str:
    if not known or value is None:
        return "-"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def log(config: Config, message: str) -> None:
    if not config.quiet:
        print(message)


def vlog(config: Config, message: str) -> None:
    if not config.quiet and config.verbose:
        print(message)


def die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument("source_dir", nargs="?")
    parser.add_argument("target_dir", nargs="?")
    parser.add_argument("--compressor")
    parser.add_argument("--compress-opts", default="")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--hosts-file", default="")
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--compare-bytes", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--list-compressors", action="store_true")
    parser.add_argument("--internal-convert")
    parser.add_argument("-h", "--help", action="store_true")
    ns = parser.parse_args(argv)
    if ns.help:
        print(usage_text(), end="")
        raise SystemExit(0)
    return ns


def default_local_jobs() -> int:
    return os.cpu_count() or 1


def env_flag(name: str) -> bool:
    return os.environ.get(name, "false") == "true"


def cli_or_env_str(cli_value: Optional[str], env_name: str, default: str = "") -> str:
    return cli_value if cli_value not in (None, "") else os.environ.get(env_name, default)


def cli_or_env_jobs(cli_value: Optional[int]) -> Optional[int]:
    if cli_value is not None:
        return cli_value
    if os.environ.get("JOBS"):
        return int(os.environ["JOBS"])
    return None


def load_config_values(ns: argparse.Namespace) -> ConfigValues:
    return ConfigValues(
        source_dir=cli_or_env_str(ns.source_dir, "SOURCE_DIR"),
        target_dir=cli_or_env_str(ns.target_dir, "TARGET_DIR"),
        compressor=cli_or_env_str(ns.compressor, "COMPRESSOR"),
        compress_opts=shlex.split(cli_or_env_str(ns.compress_opts, "COMPRESS_OPTS")),
        target_suffix=cli_or_env_str(ns.suffix, "TARGET_SUFFIX"),
        hosts_file=cli_or_env_str(ns.hosts_file, "HOSTS_FILE"),
        jobs=cli_or_env_jobs(ns.jobs),
        delete_extra=ns.delete or env_flag("DELETE_EXTRA"),
        compare_bytes=ns.compare_bytes or env_flag("COMPARE_BYTES"),
        dry_run=ns.dry_run or env_flag("DRY_RUN"),
        verbose=ns.verbose or env_flag("VERBOSE"),
        quiet=ns.quiet or env_flag("QUIET"),
    )


def get_codec(name: str) -> Codec:
    return CODECS[name]


def codec_binary(codec_name: str, purpose: str) -> str:
    codec_obj = get_codec(codec_name)
    return codec_obj.compressor_binary if purpose == "compress" else codec_obj.decompressor_binary


def require_available_codec(codec_name: str, purpose: str) -> None:
    binary = codec_binary(codec_name, purpose)
    if binary != "cat" and shutil.which(binary) is None:
        die(f"required {purpose}or for '{codec_name}' is not available")


def list_available_compressors() -> None:
    for name, codec_obj in CODECS.items():
        if codec_obj.compressor_binary == "cat" or shutil.which(codec_obj.compressor_binary):
            print(name)


def validate_tree_separation(source_dir: str, target_dir: str) -> None:
    if source_dir == target_dir:
        die("source and target must be different directories")
    if target_dir.startswith(source_dir + os.sep) or source_dir.startswith(target_dir + os.sep):
        die("source and target directories must not overlap")


def validate_config(values: ConfigValues) -> Config:
    if not values.source_dir or not values.target_dir:
        print(usage_text(), end="", file=sys.stderr)
        raise SystemExit(1)
    if not os.path.isdir(values.source_dir):
        die(f"source directory not found: {values.source_dir}")
    if not values.compressor:
        die("--compressor is required")
    if values.compressor not in CODECS:
        die(f"unknown compressor: {values.compressor}")

    require_available_codec(values.compressor, "compress")
    source_dir = os.path.realpath(values.source_dir)
    os.makedirs(values.target_dir, exist_ok=True)
    target_dir = os.path.realpath(values.target_dir)
    validate_tree_separation(source_dir, target_dir)

    target_suffix = values.target_suffix or get_codec(values.compressor).suffix
    if values.hosts_file and not os.path.isfile(values.hosts_file):
        die(f"hosts file not found: {values.hosts_file}")

    return Config(
        source_dir=source_dir,
        target_dir=target_dir,
        compressor=values.compressor,
        compress_opts=values.compress_opts,
        target_suffix=target_suffix,
        hosts_file=values.hosts_file,
        jobs=values.jobs,
        delete_extra=values.delete_extra,
        compare_bytes=values.compare_bytes,
        dry_run=values.dry_run,
        verbose=values.verbose,
        quiet=values.quiet,
    )


def load_config(ns: argparse.Namespace) -> Config:
    if ns.list_compressors:
        list_available_compressors()
        raise SystemExit(0)
    return validate_config(load_config_values(ns))


def detect_input_format(path: str) -> str:
    filename = os.path.basename(path)
    for suffix, codec_name in DETECTION_SUFFIXES:
        if filename.endswith(suffix):
            return codec_name
    return "none"


def strip_compression_suffix(path: str) -> str:
    for suffix, replacement in STRIP_SUFFIX_REPLACEMENTS.items():
        if path.endswith(suffix):
            return path[: -len(suffix)] + replacement
    for suffix in STRIP_SUFFIXES:
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


def target_rel_for(source_rel: str, target_suffix: str) -> str:
    return f"{strip_compression_suffix(source_rel)}{target_suffix}"


def build_file_task(config: Config, source_path: str, source_rel: str, source_stat: os.stat_result) -> FileTask:
    input_format = detect_input_format(source_rel)
    require_available_codec(input_format, "decompress")
    target_rel = target_rel_for(source_rel, config.target_suffix)
    return FileTask(
        source_path=source_path,
        source_rel=source_rel,
        input_format=input_format,
        target_rel=target_rel,
        target_path=os.path.join(config.target_dir, target_rel),
        input_size=source_stat.st_size,
        source_mtime_ns=source_stat.st_mtime_ns,
    )


def build_internal_task(config: Config, source_file: str) -> FileTask:
    source_rel = os.path.relpath(source_file, config.source_dir)
    return build_file_task(config, source_file, source_rel, os.stat(source_file, follow_symlinks=False))


class StreamHandle:
    def __init__(self, stream: BinaryIO, processes: list[subprocess.Popen[bytes]], owned_files: list[BinaryIO]):
        self.stream = stream
        self.processes = processes
        self.owned_files = owned_files

    def close(self) -> None:
        stream_error: Optional[BaseException] = None
        try:
            self.stream.close()
        except BaseException as exc:
            stream_error = exc
        for fh in self.owned_files:
            try:
                fh.close()
            except Exception:
                pass
        for proc in self.processes:
            ret = proc.wait()
            if ret != 0 and stream_error is None:
                stream_error = subprocess.CalledProcessError(ret, proc.args)
        if stream_error is not None:
            raise stream_error


def open_decompressed_stream(path: str, codec_name: str) -> StreamHandle:
    if codec_name == "none":
        fh = open(path, "rb")
        return StreamHandle(fh, [], [fh])
    proc = subprocess.Popen(get_codec(codec_name).decompress_command(path), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    return StreamHandle(proc.stdout, [proc], [])


def read_chunk_into(stream: BinaryIO, buffer: bytearray, view: memoryview) -> memoryview:
    count = stream.readinto(buffer)
    if count is None:
        count = 0
    return view[:count]


def copy_stream(reader: StreamHandle, writer: BinaryIO) -> int:
    buffer = bytearray(CHUNK_SIZE)
    view = memoryview(buffer)
    total = 0
    while True:
        chunk = read_chunk_into(reader.stream, buffer, view)
        if not chunk:
            return total
        writer.write(chunk)
        total += len(chunk)


def compare_streams(left_handle: StreamHandle, right_handle: StreamHandle) -> tuple[bool, int]:
    left_buffer = bytearray(CHUNK_SIZE)
    right_buffer = bytearray(CHUNK_SIZE)
    left_view = memoryview(left_buffer)
    right_view = memoryview(right_buffer)
    total = 0
    try:
        while True:
            left_chunk = read_chunk_into(left_handle.stream, left_buffer, left_view)
            right_chunk = read_chunk_into(right_handle.stream, right_buffer, right_view)
            if len(left_chunk) != len(right_chunk):
                return False, total
            if not left_chunk:
                return True, total
            if left_chunk != right_chunk:
                return False, total
            total += len(left_chunk)
    finally:
        left_handle.close()
        right_handle.close()


def write_compressed_stream(reader: StreamHandle, target_path: str, codec_name: str, opts: list[str]) -> tuple[int, int]:
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(target_path)}.", suffix=".tmp", dir=target_dir)
    os.close(fd)
    try:
        with open(tmp_path, "wb") as out_fh:
            if codec_name == "none":
                uncompressed_size = copy_stream(reader, out_fh)
            else:
                proc = subprocess.Popen(
                    get_codec(codec_name).compress_command(opts),
                    stdin=subprocess.PIPE,
                    stdout=out_fh,
                    stderr=subprocess.DEVNULL,
                )
                assert proc.stdin is not None
                try:
                    uncompressed_size = copy_stream(reader, proc.stdin)
                    proc.stdin.close()
                except Exception:
                    proc.kill()
                    raise
                ret = proc.wait()
                if ret != 0:
                    raise subprocess.CalledProcessError(ret, proc.args)
        return finalize_temp_output(tmp_path, target_path), uncompressed_size
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def finalize_temp_output(tmp_path: str, target_path: str) -> int:
    output_size = os.path.getsize(tmp_path)
    os.replace(tmp_path, target_path)
    return output_size


def can_use_external_compare() -> bool:
    return shutil.which("cmp") is not None and shutil.which("bash") is not None


def run_compare_command(script: str) -> bool:
    result = subprocess.run(["bash", "-lc", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise subprocess.CalledProcessError(result.returncode, ["bash", "-lc", script])


def decompressed_shell_command(path: str, codec_name: str) -> str:
    if codec_name == "none":
        return shlex.join(["cat", "--", path])
    return shlex.join(get_codec(codec_name).decompress_command(path))


def compare_raw_files(left_path: str, right_path: str) -> tuple[bool, int]:
    if can_use_external_compare():
        matches = subprocess.run(["cmp", "-s", "--", left_path, right_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if matches.returncode == 0:
            return True, os.path.getsize(left_path)
        if matches.returncode == 1:
            return False, 0
        raise subprocess.CalledProcessError(matches.returncode, matches.args)
    left_handle = StreamHandle(open(left_path, "rb"), [], [])
    right_handle = StreamHandle(open(right_path, "rb"), [], [])
    return compare_streams(left_handle, right_handle)


def compare_uncompressed_streams(source_path: str, source_format: str, target_path: str, target_format: str) -> tuple[bool, Optional[int]]:
    if can_use_external_compare():
        source_cmd = decompressed_shell_command(source_path, source_format)
        target_cmd = decompressed_shell_command(target_path, target_format)
        return run_compare_command(f"cmp -s <({source_cmd}) <({target_cmd})"), None
    source_handle = open_decompressed_stream(source_path, source_format)
    target_handle = open_decompressed_stream(target_path, target_format)
    matches, total = compare_streams(source_handle, target_handle)
    return matches, total if matches else None


def verified_outcome(task: FileTask, reason: str, target: TargetSnapshot, uncompressed_size: Optional[int] = None) -> TaskOutcome:
    return TaskOutcome(
        action=OutcomeAction.VERIFIED,
        source_rel=task.source_rel,
        target_rel=task.target_rel,
        reason=reason,
        input_size=task.input_size,
        output_size=target.size,
        uncompressed_size=uncompressed_size,
    )


def convert_outcome(task: FileTask, reason: str) -> TaskOutcome:
    return TaskOutcome(
        action=OutcomeAction.CONVERTED,
        source_rel=task.source_rel,
        target_rel=task.target_rel,
        reason=reason,
        input_format=task.input_format,
        input_size=task.input_size,
    )


def target_outcome(action: OutcomeAction, size: int) -> TaskOutcome:
    return TaskOutcome(action=action, output_size=size)


def plan_file_work(task: FileTask, config: Config, target: Optional[TargetSnapshot]) -> WorkItem:
    if target is None:
        return WorkItem(action=WorkAction.CONVERT, reason="target missing", task=task)
    if not stat.S_ISREG(target.mode):
        return WorkItem(action=WorkAction.CONVERT, reason="target exists but is not a regular file", task=task, target=target)
    if task.source_mtime_ns > target.mtime_ns:
        return WorkItem(action=WorkAction.CONVERT, reason="source newer than target", task=task, target=target)
    if config.compare_bytes:
        return WorkItem(action=WorkAction.VERIFY_BYTES, reason="verify uncompressed bytes", task=task, target=target)
    return WorkItem(action=WorkAction.VERIFY_METADATA, reason="target exists and mtime matches", task=task, target=target)


def plan_target_only_work(config: Config, target: TargetSnapshot) -> WorkItem:
    if config.delete_extra:
        return WorkItem(action=WorkAction.DELETE, reason="extra target file", target=target)
    return WorkItem(action=WorkAction.RETAIN, reason="extra target file", target=target)


def resolve_verification_work_item(item: WorkItem, config: Config) -> WorkItem | TaskOutcome:
    assert item.task is not None
    assert item.target is not None
    task = item.task
    target = item.target

    if item.action == WorkAction.VERIFY_METADATA:
        return verified_outcome(task, "target exists and mtime matches", target)
    matches, size = compare_uncompressed_streams(task.source_path, task.input_format, task.target_path, config.compressor)
    if matches:
        return verified_outcome(task, "mtime and uncompressed bytes match", target, uncompressed_size=size)
    return WorkItem(action=WorkAction.CONVERT, reason="uncompressed content mismatch", task=task, target=target)


def execute_convert_work_item(item: WorkItem, config: Config) -> TaskOutcome:
    assert item.task is not None
    task = item.task
    if config.dry_run:
        return convert_outcome(task, item.reason)
    reader = open_decompressed_stream(task.source_path, task.input_format)
    try:
        output_size, uncompressed_size = write_compressed_stream(reader, task.target_path, config.compressor, config.compress_opts)
    finally:
        reader.close()
    shutil.copystat(task.source_path, task.target_path, follow_symlinks=False)
    return TaskOutcome(
        action=OutcomeAction.CONVERTED,
        source_rel=task.source_rel,
        target_rel=task.target_rel,
        input_size=task.input_size,
        output_size=output_size,
        uncompressed_size=uncompressed_size,
    )


def execute_target_work_item(item: WorkItem, config: Config, reporter: Optional["Reporter"] = None) -> TaskOutcome:
    assert item.target is not None
    if item.action == WorkAction.DELETE:
        if config.dry_run:
            if reporter is None:
                vlog(config, f"would remove extra file: {item.target.rel_path}")
            else:
                reporter.vlog_line(f"would remove extra file: {item.target.rel_path}")
        else:
            os.unlink(item.target.path)
            if reporter is None:
                vlog(config, f"removed extra file: {item.target.rel_path}")
            else:
                reporter.vlog_line(f"removed extra file: {item.target.rel_path}")
        return target_outcome(OutcomeAction.DELETED, item.target.size)
    if reporter is None:
        vlog(config, f"kept extra file: {item.target.rel_path}")
    else:
        reporter.vlog_line(f"kept extra file: {item.target.rel_path}")
    return target_outcome(OutcomeAction.RETAINED, item.target.size)


def execute_work_item(item: WorkItem, config: Config) -> TaskOutcome:
    if item.action in (WorkAction.VERIFY_METADATA, WorkAction.VERIFY_BYTES):
        resolved = resolve_verification_work_item(item, config)
        if isinstance(resolved, TaskOutcome):
            return resolved
        return execute_convert_work_item(resolved, config)
    if item.action == WorkAction.CONVERT:
        return execute_convert_work_item(item, config)
    return execute_target_work_item(item, config)


def print_table_border() -> None:
    print("+----------------------+----------+------------------+------------------+------------------+")


def print_table_row(col1: str, col2: str, col3: str, col4: str, col5: str) -> None:
    print(f"| {col1:<20} | {col2:>8} | {col3:>16} | {col4:>16} | {col5:>16} |")


class ProgressDisplay:
    def __init__(self, config: Config, stats: StatsAccumulator) -> None:
        self.config = config
        self.stats = stats
        self.enabled = not config.quiet and sys.stderr.isatty()
        self.phase = "progress"
        self.last_render = 0.0
        self.last_width = 0
        self.visible = False
        self.refresh_interval = 0.25

    def start_cleanup(self) -> None:
        self.phase = "cleanup"

    def note_outcome(self, outcome: TaskOutcome) -> None:
        if outcome.action in (OutcomeAction.CONVERTED, OutcomeAction.VERIFIED):
            self.phase = "progress"

    def clear(self) -> None:
        if not self.enabled or not self.visible:
            return
        sys.stderr.write("\r" + (" " * self.last_width) + "\r")
        sys.stderr.flush()
        self.visible = False

    def render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and self.visible and now - self.last_render < self.refresh_interval:
            return
        line = self._build_line()
        padded = line
        if len(line) < self.last_width:
            padded = line + (" " * (self.last_width - len(line)))
        sys.stderr.write("\r" + padded)
        sys.stderr.flush()
        self.last_width = max(self.last_width, len(line))
        self.last_render = now
        self.visible = True

    def finish(self) -> None:
        self.clear()

    def _build_line(self) -> str:
        if self.phase == "cleanup":
            return f"cleanup: deleted {self.stats.buckets['deleted'].files} extra files"
        converted = self.stats.buckets["converted"]
        verified = self.stats.buckets["verified"]
        done = converted.files + verified.files
        input_bytes = converted.input_bytes + verified.input_bytes
        input_known = converted.input_known and verified.input_known
        output_bytes = converted.output_bytes + verified.output_bytes
        output_known = converted.output_known and verified.output_known
        verified_label = status_label("verified", self.config, lowercase=True)
        return (
            f"progress: {done} done | converted {converted.files} | "
            f"{verified_label} {verified.files} | "
            f"in {human_size(input_bytes, input_known)} | out {human_size(output_bytes, output_known)}"
        )


class Reporter:
    def __init__(self, config: Config, stats: StatsAccumulator) -> None:
        self.config = config
        self.stats = stats
        self.progress = ProgressDisplay(config, stats)

    def log_line(self, message: str) -> None:
        if self.config.quiet:
            return
        self.progress.clear()
        print(message)
        self.progress.render(force=True)

    def vlog_line(self, message: str) -> None:
        if self.config.quiet or not self.config.verbose:
            return
        self.progress.clear()
        print(message)
        self.progress.render(force=True)

    def finish_output(self) -> None:
        self.progress.finish()

    def start_cleanup_phase(self) -> None:
        self.progress.start_cleanup()
        self.progress.render(force=True)

    def handle_outcome(self, outcome: TaskOutcome) -> None:
        self.stats.add(outcome)
        self.progress.note_outcome(outcome)
        if outcome.action == OutcomeAction.CONVERTED:
            if self.config.dry_run:
                self.log_line(
                    f"convert: {outcome.source_rel} -> {outcome.target_rel} "
                    f"[{outcome.input_format} -> {self.config.compressor}; {outcome.reason}]",
                )
            else:
                self.log_line(
                    f"converted: {outcome.source_rel} -> {outcome.target_rel} "
                    f"[{human_size(outcome.input_size)} -> {human_size(outcome.output_size)}]",
                )
        elif outcome.action == OutcomeAction.VERIFIED:
            self.vlog_line(
                f"{status_label('verified', self.config, lowercase=True)}: "
                f"{outcome.source_rel} -> {outcome.target_rel} [{outcome.reason}]",
            )
        self.progress.render()

    def render_status_row(self, status: str, bucket: StatsBucket, show_input: bool) -> None:
        print_table_row(
            status_label(status, self.config),
            str(bucket.files),
            human_size(bucket.uncompressed, bucket.uncompressed_known),
            human_size(bucket.input_bytes, bucket.input_known and show_input),
            human_size(bucket.output_bytes, bucket.output_known),
        )

    def print_summary(self) -> None:
        rows = self.stats.summary_rows(self.config)
        if self.stats.buckets["converted"].files > 0 or self.config.verbose:
            print()
        print_table_border()
        print_table_row("Category", "Files", "Uncompressed", "Input", "Output")
        print_table_border()
        for index, (status, bucket, show_input) in enumerate(rows):
            if status == "total" or (status == "deleted" and index > 0):
                print_table_border()
            self.render_status_row(status, bucket, show_input)
        print_table_border()


def iter_file_entries_lex(root: str, rel_root: str = "") -> Iterator[tuple[os.DirEntry[str], str]]:
    dirs: list[os.DirEntry[str]] = []
    files: list[os.DirEntry[str]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry)
            else:
                files.append(entry)
    dirs.sort(key=lambda entry: entry.name)
    files.sort(key=lambda entry: entry.name)
    for file_entry in files:
        rel_path = os.path.join(rel_root, file_entry.name) if rel_root else file_entry.name
        yield file_entry, rel_path
    for dir_entry in dirs:
        child_rel = os.path.join(rel_root, dir_entry.name) if rel_root else dir_entry.name
        yield from iter_file_entries_lex(dir_entry.path, child_rel)


def iter_target_entries_lex(root: str) -> Iterator[TargetSnapshot]:
    for entry, rel_path in iter_file_entries_lex(root):
        if entry.is_file(follow_symlinks=False):
            stat_result = entry.stat(follow_symlinks=False)
            yield TargetSnapshot(
                rel_path=rel_path,
                path=entry.path,
                size=stat_result.st_size,
                mode=stat_result.st_mode,
                mtime_ns=stat_result.st_mtime_ns,
            )


def iter_source_tasks(config: Config) -> Iterator[FileTask]:
    for entry, rel_path in iter_file_entries_lex(config.source_dir):
        if entry.is_symlink():
            print(f"Skipping symlink: {rel_path}", file=sys.stderr)
            continue
        if not entry.is_file(follow_symlinks=False):
            print(f"Skipping unsupported file type: {rel_path}", file=sys.stderr)
            continue
        yield build_file_task(config, entry.path, rel_path, entry.stat(follow_symlinks=False))


class TargetReconciler:
    def __init__(self, config: Config, reporter: Reporter) -> None:
        self.config = config
        self.reporter = reporter
        self._target_iter = iter_target_entries_lex(config.target_dir)
        self._current = next(self._target_iter, None)

    def match_source_target(self, target_rel: str) -> Optional[TargetSnapshot]:
        while self._current is not None and self._current.rel_path < target_rel:
            self.reporter.handle_outcome(execute_target_work_item(plan_target_only_work(self.config, self._current), self.config, self.reporter))
            self._current = next(self._target_iter, None)
        if self._current is not None and self._current.rel_path == target_rel:
            matched = self._current
            self._current = next(self._target_iter, None)
            return matched
        return None

    def finish(self) -> None:
        if self.config.delete_extra:
            self.reporter.start_cleanup_phase()
        while self._current is not None:
            self.reporter.handle_outcome(execute_target_work_item(plan_target_only_work(self.config, self._current), self.config, self.reporter))
            self._current = next(self._target_iter, None)
        if self.config.delete_extra and not self.config.dry_run:
            remove_empty_directories(self.config.target_dir)


def iter_planned_file_work(config: Config, tasks: Iterator[FileTask], reconciler: TargetReconciler) -> Iterator[WorkItem]:
    for task in tasks:
        yield plan_file_work(task, config, reconciler.match_source_target(task.target_rel))


def local_executor_class(config: Config) -> type[concurrent.futures.Executor]:
    return concurrent.futures.ProcessPoolExecutor if config.compare_bytes else concurrent.futures.ThreadPoolExecutor


def remote_parallel_env(config: Config) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SOURCE_DIR": config.source_dir,
            "TARGET_DIR": config.target_dir,
            "COMPRESSOR": config.compressor,
            "COMPRESS_OPTS": " ".join(config.compress_opts),
            "TARGET_SUFFIX": config.target_suffix,
            "HOSTS_FILE": config.hosts_file,
            "JOBS": str(config.jobs or ""),
            "DELETE_EXTRA": str(config.delete_extra).lower(),
            "COMPARE_BYTES": str(config.compare_bytes).lower(),
            "DRY_RUN": str(config.dry_run).lower(),
            "VERBOSE": str(config.verbose).lower(),
            "QUIET": str(config.quiet).lower(),
        }
    )
    return env


def open_remote_parallel(config: Config) -> subprocess.Popen[bytes]:
    if shutil.which("parallel") is None:
        die("--hosts-file requires GNU parallel to be installed")
    version = subprocess.run(["parallel", "--version"], capture_output=True, text=True)
    if version.returncode != 0:
        die("--hosts-file requires GNU parallel; found a different 'parallel' implementation")
    cmd = ["parallel", "--will-cite", "-0", "--sshloginfile", config.hosts_file]
    if config.jobs:
        cmd += ["--jobs", str(config.jobs)]
    cmd += ["--", SCRIPT_PATH, "--internal-convert", "{}"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, env=remote_parallel_env(config))
    assert proc.stdin is not None
    return proc


def run_remote_parallel(config: Config, work_items: Iterator[WorkItem], reporter: Reporter) -> None:
    proc: Optional[subprocess.Popen[bytes]] = None
    try:
        for item in work_items:
            if item.action == WorkAction.CONVERT:
                assert item.task is not None
                if config.dry_run:
                    reporter.handle_outcome(execute_convert_work_item(item, config))
                else:
                    if proc is None:
                        proc = open_remote_parallel(config)
                    assert proc.stdin is not None
                    proc.stdin.write(item.task.source_path.encode() + b"\0")
                continue
            resolved = resolve_verification_work_item(item, config)
            if isinstance(resolved, TaskOutcome):
                reporter.handle_outcome(resolved)
                continue
            assert resolved.task is not None
            if config.dry_run:
                reporter.handle_outcome(execute_convert_work_item(resolved, config))
            else:
                if proc is None:
                    proc = open_remote_parallel(config)
                assert proc.stdin is not None
                proc.stdin.write(resolved.task.source_path.encode() + b"\0")
    finally:
        if proc is not None and proc.stdin is not None:
            proc.stdin.close()
    if proc is not None and proc.wait() != 0:
        raise subprocess.CalledProcessError(proc.returncode or 1, proc.args)


def run_local(config: Config, work_items: Iterator[WorkItem], reporter: Reporter) -> None:
    jobs = config.jobs or default_local_jobs()
    if jobs <= 1:
        for item in work_items:
            reporter.handle_outcome(execute_work_item(item, config))
        return
    max_pending = max(jobs * 2, 1)
    with local_executor_class(config)(max_workers=jobs) as executor:
        pending: set[concurrent.futures.Future[TaskOutcome]] = set()
        for item in work_items:
            pending.add(executor.submit(execute_work_item, item, config))
            if len(pending) >= max_pending:
                done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    reporter.handle_outcome(future.result())
        while pending:
            done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                reporter.handle_outcome(future.result())


def remove_empty_directories(root: str) -> None:
    dirs: list[os.DirEntry[str]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(entry)
    for entry in sorted(dirs, key=lambda item: item.name):
        remove_empty_directories(entry.path)
        try:
            os.rmdir(entry.path)
        except OSError:
            pass


def run_internal_convert(config: Config, source_file: str) -> None:
    task = build_internal_task(config, source_file)
    result = execute_convert_work_item(WorkItem(action=WorkAction.CONVERT, reason="remote conversion", task=task), config)
    if result.action == OutcomeAction.CONVERTED and not config.dry_run:
        log(config, f"converted: {result.source_rel} -> {result.target_rel} [{human_size(result.input_size)} -> {human_size(result.output_size)}]")


def traverse_source(config: Config) -> Iterator[FileTask]:
    return iter_source_tasks(config)


def execute_tasks(config: Config, source_tasks: Iterator[FileTask], stats: StatsAccumulator) -> TargetReconciler:
    reporter = Reporter(config, stats)
    reconciler = TargetReconciler(config, reporter)
    work_items = iter_planned_file_work(config, source_tasks, reconciler)
    if config.hosts_file:
        run_remote_parallel(config, work_items, reporter)
    else:
        run_local(config, work_items, reporter)
    return reconciler


def reconcile_target(reconciler: TargetReconciler) -> None:
    reconciler.finish()
    reconciler.reporter.finish_output()


def main(argv: list[str]) -> int:
    ns = parse_args(argv)
    config = load_config(ns)
    if ns.internal_convert:
        run_internal_convert(config, ns.internal_convert)
        return 0

    stats = StatsAccumulator()
    reconciler = execute_tasks(config, traverse_source(config), stats)
    reconcile_target(reconciler)
    if not config.hosts_file:
        Reporter(config, stats).print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
