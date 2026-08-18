#!/bin/bash
# Search a disk for raw GPS tracker logs from a given year.
#
# The tracker speaks TK103. Every fix carries `BR00` followed by `YYMMDD` and an A/V
# validity flag, which `gt02a.py` and `point.py` parse - so the year is searchable as a
# byte pattern, and a file holding it is a tracker log whatever it has been named.
#
# Written 2026-08-09 to settle whether any 2022 feed survived (it did not: two hosts,
# both passes, zero hits). Kept and generalised because old disks keep turning up, and
# because the interesting question - "is this data gone, or have I just not found it?" -
# is only answerable by a search whose empty result can be trusted.
#
#   ./find-tracker-logs.sh 2022                     # whole machine
#   ./find-tracker-logs.sh 2022 /mnt/olddisk        # one mounted disk
#   ./find-tracker-logs.sh -o ~/scans 2022 /mnt/a /mnt/b
#
# Read-only: it opens files and writes nothing outside OUTDIR. Run it under sudo to reach
# other users' files, and detached, because a whole machine takes hours:
#
#   ssh -n host 'setsid sudo /path/find-tracker-logs.sh 2022 >/dev/null 2>&1 </dev/null &'
#
# Writes four files to OUTDIR, named for the year:
#   tracker<YEAR>-hits.txt        plain files containing a fix from that year
#   tracker<YEAR>-compressed.txt  archives containing one
#   tracker<YEAR>-status.txt      self-test and progress markers
#   tracker<YEAR>-err.txt         paths that could not be read
#
# **Check the status file before believing an empty result.** An empty hits file from a
# killed run looks exactly like an empty hits file from a clean one; `ALL-DONE` is the
# only thing that separates them.
set -u

outdir=/tmp
jobs=4
large=$((200 * 1024 * 1024))

usage() { echo "usage: $0 [-o OUTDIR] [-j JOBS] [-L LARGE_BYTES] YEAR [ROOT ...]" >&2; exit 2; }

while getopts ':o:j:L:' opt; do
  case $opt in
    o) outdir=$OPTARG ;;
    j) jobs=$OPTARG ;;
    L) large=$OPTARG ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))
[ $# -ge 1 ] || usage

year=$1; shift
case $year in
  [0-9][0-9][0-9][0-9]) ;;
  *) echo "$0: YEAR must be four digits, got '$year'" >&2; exit 2 ;;
esac
roots=("$@")
[ ${#roots[@]} -gt 0 ] || roots=(/)

PAT="BR00${year#??}[01][0-9][0-3][0-9][AV]"

hits=$outdir/tracker$year-hits.txt
comp=$outdir/tracker$year-compressed.txt
status=$outdir/tracker$year-status.txt
err=$outdir/tracker$year-err.txt
mkdir -p "$outdir" || exit 1
: > "$hits"; : > "$comp"; : > "$err"; : > "$status"

say() { echo "$* $(date -Is)" >> "$status"; }

# Matching is byte-oriented and the data is binary-ish, so C collation throughout. Left to
# a UTF-8 locale, grep can reject a file as binary garbage before it ever sees the pattern.
export LC_ALL=C

# The tracker writes a whole day as one line - 460 kB and up, no newline anywhere. grep
# buffers a line at a time, so a large enough log is an out-of-memory kill; on the first
# run that showed up only as one `xargs: grep: terminated by signal 9` in the error file,
# with up to 100 files in that batch silently unsearched. Breaking on every non-alphanumeric
# byte bounds the line length, and cannot split a match because the pattern is pure
# alphanumerics. It is slower, so it is reserved for files over `large` bytes.
scan_big() { tr -c 'A-Za-z0-9' '\n' < "$1" 2>/dev/null | grep -qaE "$PAT"; }

# An empty result is the whole point of this script, so prove the pattern still works
# against known-good bytes before trusting one. This is one real record, from
# gpstracker-archive/gpstracker.raw.1625236517.bz2, with its date rewritten to the year
# being searched.
selftest() {
  local probe=$outdir/.tracker-selftest.$$ rc=0
  printf '(028042516052BR00%s0924A5953.1866N01035.3712E000.0195245200.9301000000L00000000)' \
         "${year#??}" > "$probe"
  grep -qasE "$PAT" "$probe" || rc=1
  scan_big "$probe" || rc=1
  rm -f "$probe"
  return $rc
}

say "START host=$(hostname) year=$year roots=${roots[*]}"
if selftest; then
  say "SELFTEST-OK pattern=$PAT"
else
  say "SELFTEST-FAILED pattern=$PAT - results below are meaningless, fix the pattern"
  echo "$0: self-test failed; the pattern no longer matches a known record" >&2
  exit 1
fi

# Pseudo-filesystems only. Real mounts are deliberately left in - the point is to look
# everywhere the data could be, including other disks. Pruning is by path, so it is a
# no-op when ROOT is a mounted disk rather than /, which is harmless.
prune=( -path /proc -o -path /sys -o -path /dev -o -path /run
        -o -path /var/lib/docker -o -path /snap -o -path /var/lib/lxcfs )

find "${roots[@]}" \( "${prune[@]}" \) -prune -o -type f -size -"$large"c -print0 \
     2>>"$err" \
  | xargs -0 -r -P"$jobs" -n100 grep -lasE "$PAT" >>"$hits" 2>>"$err"

find "${roots[@]}" \( "${prune[@]}" \) -prune -o -type f -size +"$large"c -print0 \
     2>>"$err" \
  | while IFS= read -r -d '' f; do
      scan_big "$f" && printf '%s\n' "$f" >>"$hits"
    done
say "PASS1-DONE hits=$(wc -l < "$hits")"

# grep cannot see inside an archive, and the 2021 feed was found as .bz2 - so this pass is
# not optional. Decompressed output is piped, so the newline problem does not arise: grep
# reads a stream it cannot seek and stops at the first match.
find "${roots[@]}" \( "${prune[@]}" \) -prune -o -type f \
     \( -name '*.gz' -o -name '*.tgz' -o -name '*.bz2' -o -name '*.xz' \
        -o -name '*.zst' -o -name '*.zip' \) -print0 2>>"$err" \
  | while IFS= read -r -d '' f; do
      case "$f" in
        *.gz|*.tgz)  zcat    -- "$f" ;;
        *.bz2)       bzcat   -- "$f" ;;
        *.xz)        xzcat   -- "$f" ;;
        *.zst)       zstdcat -- "$f" ;;
        *.zip)       unzip -p -- "$f" ;;
      esac 2>/dev/null | tr -c 'A-Za-z0-9' '\n' | grep -qaE "$PAT" \
        && printf '%s\n' "$f" >>"$comp"
    done
say "PASS2-DONE hits=$(wc -l < "$comp")"

say "ALL-DONE plain=$(wc -l < "$hits") compressed=$(wc -l < "$comp") unreadable=$(wc -l < "$err")"
