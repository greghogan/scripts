#!/usr/bin/env python3
"""
Compression Benchmark Tool
Benchmarks various compression tools (gzip, bzip2, xz, lz4, zstd, brotli)
measuring compression ratio, speed, and decompression speed.
"""

import argparse
import sys
import subprocess
import time
import json
import csv
import os
import shutil
import tempfile
from typing import List
from dataclasses import dataclass, asdict

@dataclass
class BenchmarkResult:
    file: str
    compressor: str
    level: int
    original_size: int
    compressed_size: int
    ratio: float
    comp_time: float
    decomp_time: float
    compression_rate: float
    decompression_rate: float

class Compressor:
    def __init__(self, name: str, min_level: int, max_level: int,
                 comp_cmd_tmpl: str, decomp_cmd_tmpl: str,
                 level_flag_tmpl: str = "-{}",
                 is_stream: bool = True,
                 extension: str = ""):
        self.name = name
        self.min_level = min_level
        self.max_level = max_level
        self.comp_cmd_tmpl = comp_cmd_tmpl
        self.decomp_cmd_tmpl = decomp_cmd_tmpl
        self.level_flag_tmpl = level_flag_tmpl
        self.is_stream = is_stream
        self.extension = extension # e.g., ".zip", ".7z"

    def is_available(self) -> bool:
        # Check if the binary (first word of command) exists
        binary = self.comp_cmd_tmpl.split()[0]
        return shutil.which(binary) is not None

# Define compressors
# Note: For file-based tools, {output} and {input} placeholders are used.
# Sorted alphabetically by name to ensure consistent help output and execution order.
ALL_COMPRESSORS = [
    Compressor("7z", 0, 9, "7z a -bd -y -mx={} \"{output}\" \"{input}\"", "7z x -bd -y -so \"{input}\"", level_flag_tmpl="{}", is_stream=False, extension=".7z"),
    Compressor("brotli", 0, 11, "brotli -c -q {} \"{input}\"", "brotli -d -c", level_flag_tmpl="{}", is_stream=True),
    Compressor("bzip2", 1, 9, "bzip2 -c {} \"{input}\"", "bzip2 -d -c", is_stream=True),
    Compressor("gzip", 1, 9, "gzip -c {} \"{input}\"", "gzip -d -c", is_stream=True),
    Compressor("lz4", 1, 9, "lz4 -c {} \"{input}\"", "lz4 -d -c", is_stream=True),
    Compressor("xz", 1, 9, "xz -c {} \"{input}\"", "xz -d -c", is_stream=True),
    Compressor("zip", 1, 9, "zip --quiet {} \"{output}\" \"{input}\"", "unzip -p -q \"{input}\"", is_stream=False, extension=".zip"),
    Compressor("zpaq", 1, 5, "zpaq a \"{output}\" \"{input}\" -m{}", "zpaq x \"{input}\" -to \"{temp_dir}\"", level_flag_tmpl="{}", is_stream=False, extension=".zpaq5"),
    Compressor("zstd", 1, 22, "zstd -c --ultra {} \"{input}\"", "zstd -d -c", is_stream=True),
]

def get_file_size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except FileNotFoundError:
        return 0

def run_benchmark(file_path: str, tool: Compressor, level: int) -> BenchmarkResult:
    original_size = get_file_size(file_path)

    with tempfile.TemporaryDirectory() as temp_dir:
        # Prepare Temp Files
        if tool.extension:
            temp_compressed = os.path.join(temp_dir, "compressed" + tool.extension)
        else:
            temp_compressed = os.path.join(temp_dir, "compressed")

        # Compression Command Construction
        level_flag = tool.level_flag_tmpl.format(level)

        if tool.is_stream:
            comp_cmd = tool.comp_cmd_tmpl.format(level_flag, input=file_path)
        else:
            comp_cmd = tool.comp_cmd_tmpl.format(level_flag, output=temp_compressed, input=file_path)

        # Measure Compression
        start_comp = time.perf_counter_ns()

        try:
            if tool.is_stream:
                with open(temp_compressed, 'wb') as f_out:
                    subprocess.run(comp_cmd, shell=True, check=True, stdout=f_out, stderr=subprocess.DEVNULL)
            else:
                # File based, writes directly
                subprocess.run(comp_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        except subprocess.CalledProcessError as e:
            # Temp dir cleaned up automatically
            raise e

        end_comp = time.perf_counter_ns()
        comp_time = (end_comp - start_comp) / 1_000_000_000.0

        compressed_size = get_file_size(temp_compressed)

        # Measure Decompression
        # Decompression Command Construction
        # Prepare decompress output dir for tools like zpaq
        temp_decomp_dir = os.path.join(temp_dir, "decomp")
        os.makedirs(temp_decomp_dir, exist_ok=True)

        if tool.is_stream:
            # Stream based tools usually pipe to stdout. We pipe that to /dev/null explicitly in python or shell.
            # Template is `cmd ...` which outputs to stdout.
            # Ensure we feed stdin from the compressed file
            decomp_cmd = tool.decomp_cmd_tmpl.format(input=temp_compressed, temp_dir=temp_decomp_dir) + f" < \"{temp_compressed}\" > /dev/null"
        else:
            # File based tools.
            # zpaq needs temp_dir for -to argument
            decomp_cmd = tool.decomp_cmd_tmpl.format(input=temp_compressed, temp_dir=temp_decomp_dir)

            if "zpaq" not in tool.name:
                 # zip/7z with -so or -p options pipe to stdout, so we can redirect to null if not zpaq
                 # (Unless we change 7z/zip to extract to dir, but current setup is pipe to stdout for speed/standardization where possible)
                 # Our 7z template is: 7z x -bd -y -so "{input}"
                 # Our zip template is: unzip -p -q "{input}"
                 # Both support stdout.
                 decomp_cmd += " > /dev/null"

        start_decomp = time.perf_counter_ns()

        try:
            subprocess.run(decomp_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            raise e

        end_decomp = time.perf_counter_ns()
        decomp_time = (end_decomp - start_decomp) / 1_000_000_000.0

        # Metrics
        ratio = compressed_size / original_size if original_size > 0 else 0.0
        compression_rate = original_size / comp_time if comp_time > 0 else 0.0
        decompression_rate = original_size / decomp_time if decomp_time > 0 else 0.0

        return BenchmarkResult(
            file=file_path,
            compressor=tool.name,
            level=level,
            original_size=original_size,
            compressed_size=compressed_size,
            ratio=ratio,
            comp_time=comp_time,
            decomp_time=decomp_time,
            compression_rate=compression_rate,
            decompression_rate=decompression_rate
        )

def parse_size(s: str) -> int:
    """Parses a size string like '10MB', '1KiB', '100' into bytes.
    
    Supports:
        - Plain numbers: 100, 1024
        - SI decimal suffixes (base 1000): K, KB, M, MB, G, GB
        - IEC binary suffixes (base 1024): KiB, MiB, GiB
    """
    original = s
    s = s.strip().upper()
    if not s:
        return 0
    
    multiplier = 1
    
    # Check IEC binary suffixes first (KIB, MIB, GIB) - base 1024
    if s.endswith("KIB"):
        multiplier = 1024
        s = s[:-3]
    elif s.endswith("MIB"):
        multiplier = 1024 * 1024
        s = s[:-3]
    elif s.endswith("GIB"):
        multiplier = 1024 * 1024 * 1024
        s = s[:-3]
    # SI decimal suffixes (KB, MB, GB, K, M, G) - base 1000
    elif s.endswith("KB"):
        multiplier = 1000
        s = s[:-2]
    elif s.endswith("MB"):
        multiplier = 1000 * 1000
        s = s[:-2]
    elif s.endswith("GB"):
        multiplier = 1000 * 1000 * 1000
        s = s[:-2]
    elif s.endswith("K"):
        multiplier = 1000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1000 * 1000
        s = s[:-1]
    elif s.endswith("G"):
        multiplier = 1000 * 1000 * 1000
        s = s[:-1]
    elif s.endswith("B"):
        s = s[:-1]

    try:
        return int(float(s) * multiplier)
    except ValueError:
        print(f"Error: Invalid size format '{original}'", file=sys.stderr)
        sys.exit(1)

# Table formatting helpers
TABLE_HEADERS = [
    ("Tool", 8),
    ("Lvl", 3),
    ("Original", 8),
    ("Compressed", 10),
    ("Ratio", 7),
    ("Time(C)", 8),
    ("Time(D)", 8),
    ("MB/s(C)", 8),
    ("MB/s(D)", 8)
]


def fmt_size(b: int) -> str:
    if b < 1024: return f"{b}B"
    if b < 1024*1024: return f"{b/1024:.1f}K"
    return f"{b/1024/1024:.1f}M"

def print_table_header():
    header_str = " | ".join(f"{h[0]:<{h[1]}}" for h in TABLE_HEADERS)
    print("-" * len(header_str))
    print(header_str)
    print("-" * len(header_str))
    sys.stdout.flush()

def print_table_row(r: BenchmarkResult):
    comp_mb_s = r.compression_rate / 1024 / 1024
    decomp_mb_s = r.decompression_rate / 1024 / 1024

    row = [
        f"{r.compressor:<8}",
        f"{r.level:<3}",
        f"{fmt_size(r.original_size):<8}",
        f"{fmt_size(r.compressed_size):<10}",
        f"{r.ratio:<7.3f}",
        f"{r.comp_time:<8.4f}",
        f"{r.decomp_time:<8.4f}",
        f"{comp_mb_s:<8.2f}",
        f"{decomp_mb_s:<8.2f}"
    ]
    print(" | ".join(row))
    sys.stdout.flush()

def print_table(results: List[BenchmarkResult]):
    print_table_header()
    for r in results:
        print_table_row(r)

def get_pareto_frontier(results: List[BenchmarkResult]) -> List[BenchmarkResult]:
    """
    Filter results to keep only Pareto efficient ones based on Compression Size and Compression Time.
    We want to minimize Size and minimize Time.
    A point (Time, Size) is dominated if there exists another point (Time', Size') such that:
    Time' <= Time AND Size' <= Size AND (Time' < Time OR Size' < Size)

    Since we group by file, we apply this per file.
    """
    if not results:
        return []

    # Process per file
    by_file = {}
    for r in results:
        if r.file not in by_file:
            by_file[r.file] = []
        by_file[r.file].append(r)

    pareto_results = []

    for fname, group in by_file.items():
        # Sort by Size ASC, then Time ASC
        # This makes it easier to find the frontier.
        # Valid frontier points will have strictly decreasing Time as Size increases?
        # Actually standard algo:
        # Sort by first objective (say Size ASC).
        # Iterate, keeping track of best second objective seen so far (Time).
        # If current point has Time < best_time, it's on frontier.

        # Sorting by Size ASC (Smallest Size is best)
        # Ties in Size: pick fastest (Smallest Time)
        sorted_group = sorted(group, key=lambda x: (x.compressed_size, x.comp_time))

        frontier = []
        min_time_seen = float('inf')

        for r in sorted_group:
            # If this result is faster than any result with same or smaller size seen so far
            if r.comp_time < min_time_seen:
                frontier.append(r)
                min_time_seen = r.comp_time

        pareto_results.extend(frontier)

    return pareto_results

def main():
    parser = argparse.ArgumentParser(description="Benchmark compression tools.")
    parser.add_argument("input_file", help="File to benchmark")
    parser.add_argument("--format", nargs="+", choices=["csv", "json", "table"], default=["table"], help="Output format(s)")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs to average results over")
    parser.add_argument("--tools", nargs="+", choices=[t.name for t in ALL_COMPRESSORS], help="Select specific compression tools to run")
    parser.add_argument("--head", metavar="SIZE", help="Benchmark only the first SIZE bytes. SIZE is a number with optional suffix: K/KB/KiB, M/MB/MiB, G/GB/GiB (e.g., 10MiB, 1KB, 500)")
    args = parser.parse_args()

    if not os.path.isfile(args.input_file):
        print(f"Error: '{args.input_file}' is not a valid file.", file=sys.stderr)
        sys.exit(1)

    input_file = args.input_file
    results = []

    available_tools = [t for t in ALL_COMPRESSORS if t.is_available()]

    # Filter tools if requested
    if args.tools:
        available_tools = [t for t in available_tools if t.name in args.tools]

    if not available_tools:
        print("No supported compression tools found (or none matched using --tools).", file=sys.stderr)
        sys.exit(1)

    # Single File Mode
    if not os.access(input_file, os.R_OK):
        print(f"Error: Skipping unreadable file: {input_file}", file=sys.stderr)
        sys.exit(1)

    temp_head_file = None
    if args.head:
        limit_bytes = parse_size(args.head)
        try:
            # Create a temp file for the truncated content
            # We use delete=False to keep it available for the benchmark, and remove it manually
            tf = tempfile.NamedTemporaryFile(delete=False, prefix="bench_head_")
            temp_head_file = tf.name

            with open(input_file, 'rb') as f_in, open(temp_head_file, 'wb') as f_out:
                data = f_in.read(limit_bytes)
                f_out.write(data)

            # Use this temp file as the input
            input_file = temp_head_file
            # Force close the temp file so subprocesses can read it safely
            tf.close()

        except OSError as e:
            print(f"Error creating head sample: {e}", file=sys.stderr)
            if temp_head_file and os.path.exists(temp_head_file):
                os.remove(temp_head_file)
            sys.exit(1)

    try:
        # Print header for streaming output
        if "table" in args.format:
            print_table_header()
        
        for tool in available_tools:
            for level in range(tool.min_level, tool.max_level + 1):
                comp_time_sum = 0.0
                decomp_time_sum = 0.0
                last_res = None
                valid_run = False

                for r_idx in range(args.runs):
                    try:
                        res = run_benchmark(input_file, tool, level)
                        comp_time_sum += res.comp_time
                        decomp_time_sum += res.decomp_time
                        last_res = res
                        valid_run = True
                    except subprocess.CalledProcessError as e:
                        print(f"Error running {tool.name} level {level} on {input_file}: {e}", file=sys.stderr)

                if valid_run and last_res:
                    avg_comp_time = comp_time_sum / args.runs
                    avg_decomp_time = decomp_time_sum / args.runs

                    # Recalculate speeds based on average time
                    compression_rate = last_res.original_size / avg_comp_time if avg_comp_time > 0 else 0.0
                    decompression_rate = last_res.original_size / avg_decomp_time if avg_decomp_time > 0 else 0.0

                    # Update result with averaged values
                    last_res.comp_time = avg_comp_time
                    last_res.decomp_time = avg_decomp_time
                    last_res.compression_rate = compression_rate
                    last_res.decompression_rate = decompression_rate

                    results.append(last_res)
                    
                    # Stream output for table format
                    if "table" in args.format:
                        print_table_row(last_res)

    finally:
        # Cleanup temp head file if it was created
        if temp_head_file and os.path.exists(temp_head_file):
            os.remove(temp_head_file)

    # Filter Pareto Frontier
    pareto_results = get_pareto_frontier(results)
    pareto_results.sort(key=lambda x: x.compression_rate, reverse=True)  # Sort by compression_rate (MB/s) descending

    # Output
    if "table" in args.format:
        # Print Pareto summary after streaming all rows
        print()
        print("Pareto-efficient results:")
        print_table_header()
        for r in pareto_results:
            print_table_row(r)

    if "json" in args.format:
        json_output = []
        for r in results:
            d = asdict(r)
            del d['file']
            json_output.append(d)
        print(json.dumps(json_output, indent=2))

    if "csv" in args.format:
        # Determine strict fields from dataclass, exclude file
        fieldnames = [field for field in BenchmarkResult.__annotations__ if field != "file"]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            d = asdict(r)
            del d['file']
            writer.writerow(d)

if __name__ == "__main__":
    main()
