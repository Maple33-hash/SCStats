from __future__ import annotations
import sys
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import os  
from typing import Optional, Dict, Any, List, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QSize, QEvent
from PySide6.QtGui import QPalette, QColor, QCursor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QTabWidget,
    QLabel,
    QProgressBar,
    QFrame,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSizePolicy,
    QFrame,
    QSpacerItem,
    QCheckBox,
    QMessageBox,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import random  

def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for dev and for PyInstaller --onefile.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)




HEAD_READ_SIZE = 64 * 1024
TAIL_READ_SIZE = 64 * 1024

END_MISSION_RE = re.compile(
    r"<EndMission>.*?CompletionType\[(?P<completion_type>[^\]]+)\]",
    re.IGNORECASE,
)

SHOP_BUY_RE = re.compile(
    r"CEntityComponentShopUIProvider::SendShopBuyRequest.*?"
    r"shopName\[(?P<shop_name>[^\]]+)\].*?"
    r"client_price\[(?P<price>[^\]]+)\].*?"
    r"itemName\[(?P<item_name>[^\]]+)\].*?"
    r"quantity\[(?P<qty>[^\]]+)\]",
    re.IGNORECASE,
)

LOGIN_RE = re.compile(
    r"User Login Success - Handle\[(?P<handle>[^\]]+)\]"
)

ACTOR_DEATH_RE = re.compile(
    r"<Actor Death>\s+CActor::Kill:\s+'(?P<victim>[^']+)'\s+\[\d+\].*?"
    r"killed by\s+'(?P<killer>[^']+)'\s+\[\d+\].*?"
    r"using\s+'(?P<weapon>[^']+)'.*?"
    r"with damage type\s+'(?P<dtype>[^']+)'",
    re.IGNORECASE,
)

NPC_NAME_RE = re.compile(r"\d{6}$")


def format_human(n: float) -> str:
    """Format numbers like 1234 -> '1,234.00 (1.23k)'."""
    abs_n = abs(n)
    base = f"{n:,.2f}"
    if abs_n >= 1_000_000_000_000:
        return f"{base} ({n / 1_000_000_000_000:.2f} trillion)"
    elif abs_n >= 1_000_000_000:
        return f"{base} ({n / 1_000_000_000:.2f} billion)"
    elif abs_n >= 1_000_000:
        return f"{base} ({n / 1_000_000:.2f} million)"
    elif abs_n >= 1_000:
        return f"{base} ({n / 1_000:.2f}k)"
    else:
        return base


def format_human_with_unit(n: float, unit: str = "aUEC") -> str:
    """
    Format numbers with a unit after the raw value, e.g.
    1234 -> '1,234.00 aUEC (1.23k)'.
    """
    abs_n = abs(n)
    base = f"{n:,.2f} {unit}"
    if abs_n >= 1_000_000_000_000:
        return f"{base} ({n / 1_000_000_000_000:.2f} trillion)"
    elif abs_n >= 1_000_000_000:
        return f"{base} ({n / 1_000_000_000:.2f} billion)"
    elif abs_n >= 1_000_000:
        return f"{base} ({n / 1_000_000:.2f} million)"
    elif abs_n >= 1_000:
        return f"{base} ({n / 1_000:.2f}k)"
    else:
        return base


def format_ts_str(ts: Optional[str]) -> str:
    """Format ISO timestamp string into 'YYYY-MM-DD HH:MM:SS'."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def extract_ts_from_line(line: str) -> Optional[datetime]:
    start = line.find("<")
    if start == -1:
        return None
    end = line.find(">", start + 1)
    if end == -1:
        return None
    ts_str = line[start + 1:end]
    if not ts_str.endswith("Z"):
        return None
    ts_str = ts_str[:-1]
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def parse_version_from_line(line: str) -> Optional[str]:
    if "ProductVersion:" in line:
        return line.split("ProductVersion:", 1)[1].strip()
    if "FileVersion:" in line:
        return line.split("FileVersion:", 1)[1].strip()
    return None


def normalize_version(v: str) -> str:
    if v == "UNKNOWN":
        return v
    parts = v.split(".")
    if len(parts) < 3:
        return v
    major, minor, third = parts[0], parts[1], parts[2]
    patch_digit = third[0] if third else "0"
    return f"{major}.{minor}.{patch_digit}"


def normalize_name(name: str) -> str:
    n = name.strip()
    if n.lower() == "unknown":
        return "<unknown player name>"
    return n


def is_npc_name(name: str) -> bool:
    return bool(NPC_NAME_RE.search(name))


def clean_weapon_name(raw_weapon: str) -> str:
    w = raw_weapon.strip()
    w = re.sub(r"([ _-]?\d{4,})$", "", w)
    return w.strip() or raw_weapon.strip()


def clean_npc_label(raw_name: str) -> str:
    base = re.sub(r"([ _-]?\d{4,})$", "", raw_name).strip()
    return base or raw_name.strip()


def get_head_info(path: Path):
    with path.open("rb") as f:
        data = f.read(HEAD_READ_SIZE)
    text = data.decode("utf-8", errors="ignore")

    first_ts: Optional[datetime] = None
    version: Optional[str] = None

    for line in text.splitlines():
        if first_ts is None:
            ts = extract_ts_from_line(line)
            if ts:
                first_ts = ts
        if version is None:
            v = parse_version_from_line(line)
            if v:
                version = v
        if first_ts is not None and version is not None:
            break

    if first_ts is None:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                ts = extract_ts_from_line(line)
                if ts:
                    first_ts = ts
                    break

    if version is None:
        version = "UNKNOWN"

    return first_ts, version


def find_last_timestamp(path: Path) -> Optional[datetime]:
    size = path.stat().st_size
    read_size = min(TAIL_READ_SIZE, size)
    with path.open("rb") as f:
        f.seek(size - read_size)
        data = f.read()
    text = data.decode("utf-8", errors="ignore")

    for line in reversed(text.splitlines()):
        ts = extract_ts_from_line(line)
        if ts:
            return ts

    last_ts = None
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ts = extract_ts_from_line(line)
            if ts:
                last_ts = ts
    return last_ts


def analyze_single_log(path: Path) -> Dict[str, Any]:
    start_ts, version = get_head_info(path)
    end_ts = find_last_timestamp(path)

    if not start_ts or not end_ts or end_ts < start_ts:
        return {
            "duration": 0,
            "day": None,
            "version": None,
            "start_ts": None,
            "end_ts": None,
        }

    duration = int((end_ts - start_ts).total_seconds())
    day = start_ts.date().isoformat()
    return {
        "duration": duration,
        "day": day,
        "version": version,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }



class AnalyzerThread(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, folder: str):
        super().__init__()
        self.folder = folder

    def run(self):
        try:
            folder_path = Path(self.folder)
            if not folder_path.exists():
                self.failed.emit(f"Folder not found: {self.folder}")
                return

            files = [p for p in folder_path.iterdir() if p.is_file()]
            total_files = len(files)

            total_seconds = 0
            sessions = 0
            malformed = 0
            day_totals: Dict[str, int] = {}
            version_data: Dict[str, Dict[str, Any]] = {}
            earliest_start: Optional[datetime] = None
            latest_end: Optional[datetime] = None
            session_times: List[Tuple[datetime, datetime]] = []

            mission_completion_counts: Dict[str, int] = {}
            mission_first_ts: Optional[datetime] = None
            mission_last_ts: Optional[datetime] = None

            global_shops = defaultdict(lambda: {"count": 0, "spent": 0.0})
            global_items = defaultdict(lambda: {"count": 0, "spent": 0.0})
            global_earliest_purchase = None    
            global_latest_purchase = None      
            sessions_with_spending = 0
            max_session_spent = 0.0
            max_session_file: Optional[Path] = None
            max_session_first_ts: Optional[datetime] = None
            max_session_breakdown = None
            global_max_purchase = None  

            combat_total_kills = 0
            combat_total_deaths = 0
            combat_kills_vs_players = 0
            combat_kills_vs_npcs = 0
            combat_suicides = 0
            combat_ragequits = 0
            combat_global_max_kill_streak = 0

            combat_global_nemesis: Dict[str, int] = {}
            combat_global_reverse_nemesis: Dict[str, int] = {}
            combat_global_deaths_by_dtype: Dict[str, int] = {}
            combat_global_kills_by_weapon: Dict[str, int] = {}
            combat_global_npc_kills_by_type: Dict[str, int] = {}

            combat_all_kill_ts: List[datetime] = []
            combat_all_death_ts: List[datetime] = []

            combat_global_first_kill = None  
            combat_global_first_death = None 

            combat_life_sum_seconds = 0.0
            combat_life_count = 0

            combat_best_session_kills = 0
            combat_best_session_file: Optional[Path] = None



            total_lines = 0
            insurance_claims = 0
            vehicle_events: List[Tuple[datetime, int]] = []

            for idx, path in enumerate(files, start=1):
                res = analyze_single_log(path)
                duration = res["duration"]

                start_ts = res["start_ts"]
                end_ts = res["end_ts"]

                if duration <= 0:
                    malformed += 1
                else:
                    total_seconds += duration
                    sessions += 1

                    day = res["day"]
                    version = res["version"]

                    if day:
                        day_totals[day] = day_totals.get(day, 0) + duration

                    if version:
                        norm_version = normalize_version(version)
                        if norm_version not in version_data:
                            version_data[norm_version] = {
                                "seconds": 0,
                                "earliest": None,
                                "latest": None,
                            }
                        vinfo = version_data[norm_version]
                        vinfo["seconds"] += duration
                        if start_ts:
                            if vinfo["earliest"] is None or start_ts < vinfo["earliest"]:
                                vinfo["earliest"] = start_ts
                        if end_ts:
                            if vinfo["latest"] is None or end_ts > vinfo["latest"]:
                                vinfo["latest"] = end_ts

                    if start_ts:
                        if earliest_start is None or start_ts < earliest_start:
                            earliest_start = start_ts
                    if end_ts:
                        if latest_end is None or end_ts > latest_end:
                            latest_end = end_ts

                    if start_ts and end_ts:
                        session_times.append((start_ts, end_ts))

                handle: Optional[str] = None
                file_kills_total = 0
                file_deaths_total = 0
                file_kills_vs_players = 0
                file_kills_vs_npcs = 0
                file_suicides = 0
                file_ragequits = 0
                file_max_kill_streak = 0
                current_kill_streak = 0

                file_nemesis: Dict[str, int] = {}
                file_reverse_nemesis: Dict[str, int] = {}
                file_npc_kills_by_type: Dict[str, int] = {}
                file_deaths_by_dtype: Dict[str, int] = {}
                file_kills_by_weapon: Dict[str, int] = {}
                file_kill_timestamps: List[datetime] = []
                file_death_timestamps: List[datetime] = []

                file_first_kill = None  
                file_first_death = None 

                death_events_for_ragequit: List[Tuple[datetime, str, str]] = []

                file_life_sum_seconds = 0.0
                file_life_count = 0

                file_spent_total = 0.0
                file_breakdown = defaultdict(lambda: defaultdict(float))
                file_first_purchase_ts: Optional[datetime] = None
                file_max_purchase = None  

                try:
                    with path.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            total_lines += 1
                            if "User Login Success - Handle[" in line:
                                m_h = LOGIN_RE.search(line)
                                if m_h:
                                    handle = m_h.group("handle").strip()

                            if "<Actor Death>" in line:
                                ts = extract_ts_from_line(line)
                                if not ts:
                                    pass
                                else:
                                    m_ad = ACTOR_DEATH_RE.search(line)
                                    if m_ad:
                                        victim_raw = m_ad.group("victim").strip()
                                        killer_raw = m_ad.group("killer").strip()
                                        weapon_raw = m_ad.group("weapon").strip()
                                        dtype = (m_ad.group("dtype") or "").strip() or "Unknown"

                                        victim_is_npc = is_npc_name(victim_raw)
                                        killer_is_npc = is_npc_name(killer_raw)

                                        victim = normalize_name(victim_raw)
                                        killer = normalize_name(killer_raw)

                                        if handle and victim_raw == handle:
                                            file_deaths_total += 1
                                            file_death_timestamps.append(ts)

                                            if start_ts is not None:
                                                delta = (ts - start_ts).total_seconds()
                                                if delta >= 0:
                                                    file_life_sum_seconds += delta
                                                    file_life_count += 1

                                            file_deaths_by_dtype[dtype] = (
                                                file_deaths_by_dtype.get(dtype, 0) + 1
                                            )

                                            if killer_raw != handle:
                                                if killer_is_npc:
                                                    label = clean_npc_label(killer_raw)
                                                else:
                                                    label = killer
                                                file_nemesis[label] = file_nemesis.get(label, 0) + 1

                                            if file_first_death is None:
                                                k_name = clean_npc_label(killer_raw) if killer_is_npc else killer
                                                file_first_death = (ts, k_name, dtype)

                                            current_kill_streak = 0
                                            death_events_for_ragequit.append((ts, victim_raw, killer_raw))

                                        if handle and killer_raw == handle:
                                            file_kills_total += 1
                                            file_kill_timestamps.append(ts)

                                            if victim_raw == handle:
                                                file_suicides += 1

                                            if victim_is_npc:
                                                file_kills_vs_npcs += 1
                                                npc_label = clean_npc_label(victim_raw)
                                                file_npc_kills_by_type[npc_label] = (
                                                    file_npc_kills_by_type.get(npc_label, 0) + 1
                                                )
                                            else:
                                                if victim_raw != handle:
                                                    file_kills_vs_players += 1
                                                    v_name = victim
                                                    file_reverse_nemesis[v_name] = (
                                                        file_reverse_nemesis.get(v_name, 0) + 1
                                                    )

                                            weapon = clean_weapon_name(weapon_raw)
                                            file_kills_by_weapon[weapon] = (
                                                file_kills_by_weapon.get(weapon, 0) + 1
                                            )

                                            if file_first_kill is None and victim_raw != handle:
                                                vk_name = clean_npc_label(victim_raw) if victim_is_npc else victim
                                                file_first_kill = (ts, vk_name, weapon)

                                            current_kill_streak += 1
                                            if current_kill_streak > file_max_kill_streak:
                                                file_max_kill_streak = current_kill_streak

                            if "<EndMission>" in line:
                                m = END_MISSION_RE.search(line)
                                if m:
                                    ctype = m.group("completion_type").strip()
                                    mission_completion_counts[ctype] = (
                                        mission_completion_counts.get(ctype, 0) + 1
                                    )
                                    ts = extract_ts_from_line(line)
                                    if ts:
                                        if mission_first_ts is None or ts < mission_first_ts:
                                            mission_first_ts = ts
                                        if mission_last_ts is None or ts > mission_last_ts:
                                            mission_last_ts = ts

                            if "CEntityComponentShopUIProvider::SendShopBuyRequest" in line:
                                m2 = SHOP_BUY_RE.search(line)
                                if not m2:
                                    continue

                                ts = extract_ts_from_line(line)
                                shop_name = m2.group("shop_name").strip()
                                item_name = m2.group("item_name").strip()
                                price_str = m2.group("price").strip()
                                qty_str = m2.group("qty").strip()

                                try:
                                    price = float(price_str)
                                    qty = float(qty_str)
                                except ValueError:
                                    continue

                                spent = price * qty
                                file_spent_total += spent
                                file_breakdown[shop_name][item_name] += spent

                                global_shops[shop_name]["count"] += 1
                                global_shops[shop_name]["spent"] += spent
                                global_items[item_name]["count"] += 1
                                global_items[item_name]["spent"] += spent

                                if ts:
                                    record = (ts, shop_name, item_name, spent)
                                    if (
                                        global_earliest_purchase is None
                                        or ts < global_earliest_purchase[0]
                                    ):
                                        global_earliest_purchase = record
                                    if (
                                        global_latest_purchase is None
                                        or ts > global_latest_purchase[0]
                                    ):
                                        global_latest_purchase = record

                                    if file_first_purchase_ts is None or ts < file_first_purchase_ts:
                                        file_first_purchase_ts = ts

                                if file_max_purchase is None or spent > file_max_purchase[0]:
                                    file_max_purchase = (spent, ts, shop_name, item_name)

                            

                            if "<CWallet::ProcessClaimToNextStep>" in line and "New Insurance Claim Request" in line:
                                insurance_claims += 1


                            if "Fetching vehicle list" in line and "Retrieved" in line:

                                m_vehicle = re.search(r"Retrieved\s+(\d+)", line)
                                if m_vehicle:
                                    try:
                                        count = int(m_vehicle.group(1))
                                    except ValueError:
                                        count = None
                                    ts_event = extract_ts_from_line(line)
                                    if ts_event and count is not None:
                                        vehicle_events.append((ts_event, count))

                except Exception:
                    pass  

                
                if handle and end_ts:
                    for ts, victim_raw, killer_raw in death_events_for_ragequit:
                        if victim_raw == handle and killer_raw != handle:
                            delta = (end_ts - ts).total_seconds()
                            if 0 < delta <= 10:
                                file_ragequits += 1

                combat_total_kills += file_kills_total
                combat_total_deaths += file_deaths_total
                combat_kills_vs_players += file_kills_vs_players
                combat_kills_vs_npcs += file_kills_vs_npcs
                combat_suicides += file_suicides
                combat_ragequits += file_ragequits

                if file_max_kill_streak > combat_global_max_kill_streak:
                    combat_global_max_kill_streak = file_max_kill_streak

                for name, count in file_nemesis.items():
                    combat_global_nemesis[name] = combat_global_nemesis.get(name, 0) + count

                for name, count in file_reverse_nemesis.items():
                    combat_global_reverse_nemesis[name] = (
                        combat_global_reverse_nemesis.get(name, 0) + count
                    )

                for dt, c in file_deaths_by_dtype.items():
                    combat_global_deaths_by_dtype[dt] = (
                        combat_global_deaths_by_dtype.get(dt, 0) + c
                    )

                for w, c in file_kills_by_weapon.items():
                    combat_global_kills_by_weapon[w] = (
                        combat_global_kills_by_weapon.get(w, 0) + c
                    )

                for npc_label, c in file_npc_kills_by_type.items():
                    combat_global_npc_kills_by_type[npc_label] = (
                        combat_global_npc_kills_by_type.get(npc_label, 0) + c
                    )

                combat_all_kill_ts.extend(file_kill_timestamps)
                combat_all_death_ts.extend(file_death_timestamps)

                if file_first_kill is not None:
                    ts_fk, victim_fk, weapon_fk = file_first_kill
                    if (
                        combat_global_first_kill is None
                        or ts_fk < combat_global_first_kill[0]
                    ):
                        combat_global_first_kill = (ts_fk, victim_fk, weapon_fk, path)

                if file_first_death is not None:
                    ts_fd, killer_fd, dtype_fd = file_first_death
                    if (
                        combat_global_first_death is None
                        or ts_fd < combat_global_first_death[0]
                    ):
                        combat_global_first_death = (ts_fd, killer_fd, dtype_fd, path)

                combat_life_sum_seconds += file_life_sum_seconds
                combat_life_count += file_life_count

                if file_kills_total > combat_best_session_kills:
                    combat_best_session_kills = file_kills_total
                    combat_best_session_file = path

                if file_spent_total > 0:
                    sessions_with_spending += 1
                    if file_spent_total > max_session_spent:
                        max_session_spent = file_spent_total
                        max_session_file = path
                        max_session_first_ts = file_first_purchase_ts
                        max_session_breakdown = file_breakdown

                if file_max_purchase is not None:
                    spent_local, ts_local, shop_local, item_local = file_max_purchase
                    if (
                        global_max_purchase is None
                        or spent_local > global_max_purchase[0]
                    ):
                        global_max_purchase = (
                            spent_local,
                            ts_local,
                            shop_local,
                            item_local,
                            path,
                        )

                self.progress.emit(idx, total_files)

            avg_session = total_seconds / sessions if sessions else 0
            avg_per_day = (
                sum(day_totals.values()) / len(day_totals) if day_totals else 0
            )

            most_played = None
            if version_data:
                most_played = max(
                    ((v, d["seconds"]) for v, d in version_data.items()),
                    key=lambda x: x[1],
                )

            longest_day = None
            if day_totals:
                day, secs = max(day_totals.items(), key=lambda x: x[1])
                longest_day = {"day": day, "seconds": secs}

            biggest_gap = None
            if session_times:
                session_times.sort(key=lambda t: t[0])
                max_gap_seconds = -1
                gap_from = None
                gap_to = None
                for i in range(1, len(session_times)):
                    prev_end = session_times[i - 1][1]
                    curr_start = session_times[i][0]
                    gap = (curr_start - prev_end).total_seconds()
                    if gap > max_gap_seconds:
                        max_gap_seconds = gap
                        gap_from = prev_end
                        gap_to = curr_start
                if max_gap_seconds >= 0:
                    biggest_gap = {
                        "seconds": int(max_gap_seconds),
                        "from": gap_from.isoformat() if gap_from else None,
                        "to": gap_to.isoformat() if gap_to else None,
                    }

            per_version_json = {}
            for ver, info in version_data.items():
                per_version_json[ver] = {
                    "seconds": info["seconds"],
                    "earliest": info["earliest"].isoformat()
                    if info["earliest"]
                    else None,
                    "latest": info["latest"].isoformat() if info["latest"] else None,
                }

            mission_stats = {
                "completion_counts": mission_completion_counts,
                "total_events": sum(mission_completion_counts.values()),
                "first_end": mission_first_ts.isoformat()
                if mission_first_ts
                else None,
                "last_end": mission_last_ts.isoformat() if mission_last_ts else None,
            }

            total_spent = sum(s["spent"] for s in global_shops.values())
            total_purchases = sum(s["count"] for s in global_shops.values())
            distinct_shops = len(global_shops)
            distinct_items = len(global_items)

            if sessions_with_spending:
                avg_spent_session = total_spent / sessions_with_spending
            else:
                avg_spent_session = 0.0

            first_purchase = None
            last_purchase = None
            if global_earliest_purchase:
                ts, shop, item, spent = global_earliest_purchase
                first_purchase = {
                    "time": ts.isoformat(),
                    "shop": shop,
                    "item": item,
                    "spent": spent,
                }
            if global_latest_purchase:
                ts, shop, item, spent = global_latest_purchase
                last_purchase = {
                    "time": ts.isoformat(),
                    "shop": shop,
                    "item": item,
                    "spent": spent,
                }

            max_session = None
            if max_session_file is not None:
                breakdown_dict = {}
                for shop, items in max_session_breakdown.items():
                    breakdown_dict[shop] = dict(items)
                max_session = {
                    "file": max_session_file.name,
                    "time": max_session_first_ts.isoformat()
                    if max_session_first_ts
                    else None,
                    "spent": max_session_spent,
                    "breakdown": breakdown_dict,
                }

            max_purchase = None
            if global_max_purchase:
                spent_mp, ts_mp, shop_mp, item_mp, path_mp = global_max_purchase
                max_purchase = {
                    "spent": spent_mp,
                    "time": ts_mp.isoformat() if ts_mp else None,
                    "shop": shop_mp,
                    "item": item_mp,
                    "file": path_mp.name,
                }

            shops_dict = {k: dict(v) for k, v in global_shops.items()}
            items_dict = {k: dict(v) for k, v in global_items.items()}

            spending_stats = {
                "total_spent": total_spent,
                "total_purchases": total_purchases,
                "distinct_shops": distinct_shops,
                "distinct_items": distinct_items,
                "sessions_with_purchases": sessions_with_spending,
                "average_spent_per_session": avg_spent_session,
                "shops": shops_dict,
                "items": items_dict,
                "first_purchase": first_purchase,
                "last_purchase": last_purchase,
                "max_session": max_session,
                "max_purchase": max_purchase,
            }

            if total_seconds > 0:
                total_hours_played = total_seconds / 3600.0
                kills_per_hour = (
                    combat_total_kills / total_hours_played
                    if total_hours_played > 0
                    else 0.0
                )
            else:
                kills_per_hour = 0.0

            if combat_total_deaths > 0:
                kd_ratio = combat_total_kills / combat_total_deaths
            else:
                kd_ratio = float(combat_total_kills)

            if combat_life_count > 0:
                overall_avg_life_seconds = combat_life_sum_seconds / combat_life_count
            else:
                overall_avg_life_seconds = None

            top_nemesis = sorted(
                combat_global_nemesis.items(), key=lambda x: x[1], reverse=True
            )[:50]
            top_reverse_nemesis = sorted(
                combat_global_reverse_nemesis.items(), key=lambda x: x[1], reverse=True
            )[:50]

            kill_ts_strings = [dt.isoformat() for dt in combat_all_kill_ts]
            death_ts_strings = [dt.isoformat() for dt in combat_all_death_ts]

            first_kill = None
            if combat_global_first_kill is not None:
                ts_fk, victim_fk, weapon_fk, path_fk = combat_global_first_kill
                first_kill = {
                    "time": ts_fk.isoformat(),
                    "victim": victim_fk,
                    "weapon": weapon_fk,
                    "file": path_fk.name,
                }

            first_death = None
            if combat_global_first_death is not None:
                ts_fd, killer_fd, dtype_fd, path_fd = combat_global_first_death
                first_death = {
                    "time": ts_fd.isoformat(),
                    "killer": killer_fd,
                    "damage_type": dtype_fd,
                    "file": path_fd.name,
                }

            best_session_file_name = (
                combat_best_session_file.name
                if combat_best_session_file is not None
                else None
            )

            combat_stats = {
                "total_kills": combat_total_kills,
                "total_deaths": combat_total_deaths,
                "kills_vs_players": combat_kills_vs_players,
                "kills_vs_npcs": combat_kills_vs_npcs,
                "suicides": combat_suicides,
                "ragequits": combat_ragequits,
                "kd_ratio": kd_ratio,
                "kills_per_hour": kills_per_hour,
                "max_kill_streak": combat_global_max_kill_streak,
                "overall_avg_life_seconds": overall_avg_life_seconds,
                "best_session_kills": combat_best_session_kills,
                "best_session_file": best_session_file_name,
                "nemesis": top_nemesis,
                "reverse_nemesis": top_reverse_nemesis,
                "npc_kills_by_type": combat_global_npc_kills_by_type,
                "deaths_by_damage_type": combat_global_deaths_by_dtype,
                "kills_by_weapon": combat_global_kills_by_weapon,
                "kill_timestamps": kill_ts_strings,
                "death_timestamps": death_ts_strings,
                "first_kill": first_kill,
                "first_death": first_death,
            }

            
            if session_times:
                first_start_by_day: Dict[datetime.date, datetime] = {}
                last_end_by_day: Dict[datetime.date, datetime] = {}
                for s_ts, e_ts in session_times:
                    day = s_ts.date()
                    if day not in first_start_by_day or s_ts < first_start_by_day[day]:
                        first_start_by_day[day] = s_ts
                    if day not in last_end_by_day or e_ts > last_end_by_day[day]:
                        last_end_by_day[day] = e_ts
                sum_start_seconds = 0.0
                sum_end_seconds = 0.0
                for start_dt in first_start_by_day.values():
                    sum_start_seconds += (
                        start_dt.hour * 3600 + start_dt.minute * 60 + start_dt.second
                    )
                for end_dt in last_end_by_day.values():
                    sum_end_seconds += (
                        end_dt.hour * 3600 + end_dt.minute * 60 + end_dt.second
                    )
                count_days = len(first_start_by_day)
                if count_days > 0:
                    avg_start_secs = sum_start_seconds / count_days
                    avg_end_secs = sum_end_seconds / count_days

                    def _secs_to_hm(secs: float) -> str:
                        hrs = int(secs // 3600) % 24
                        mins = int((secs % 3600) // 60)
                        return f"{hrs:02d}:{mins:02d}"

                    avg_start_time_str = _secs_to_hm(avg_start_secs)
                    avg_end_time_str = _secs_to_hm(avg_end_secs)
                else:
                    avg_start_time_str = None
                    avg_end_time_str = None
            else:
                avg_start_time_str = None
                avg_end_time_str = None

           
            log_span_str = None
            if earliest_start and latest_end:
                try:
                    delta = latest_end - earliest_start
                    days = delta.total_seconds() / 86400.0
                    if days >= 365:
                        years = days / 365.0
                        log_span_str = f"{years:.2f} years"
                    elif days >= 1:
                        log_span_str = f"{int(days)} days"
                    else:
                        hours = delta.total_seconds() / 3600.0
                        log_span_str = f"{hours:.1f} hours"
                except Exception:
                    log_span_str = None
            other_stats = {
                "log_span": log_span_str,
                "total_files": total_files,
                "total_lines": total_lines,
                "insurance_claims": insurance_claims,
                "malformed": malformed,
                "mission_completion_counts": mission_completion_counts,
            }

            result = {
                "total_seconds": total_seconds,
                "average_seconds": avg_session,
                "average_per_day_seconds": avg_per_day,
                "sessions": sessions,
                "days_played": len(day_totals),
                "per_version": per_version_json,
                "earliest_start": earliest_start.isoformat()
                if earliest_start
                else None,
                "latest_end": latest_end.isoformat() if latest_end else None,
                "most_played": {
                    "version": most_played[0],
                    "seconds": most_played[1],
                }
                if most_played
                else None,
                "malformed": malformed,
                "longest_day": longest_day,
                "biggest_gap": biggest_gap,
                "total_files": total_files,
                "missions": mission_stats,
                "spending": spending_stats,
                "combat": combat_stats,
                "other": other_stats,
                "day_totals": day_totals,
            }

            self.finished_ok.emit(result)

        except Exception as e:
            self.failed.emit(str(e))



class StatCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "-",
        subtitle: str = "",
        tooltip: str = "",
    ):
        super().__init__()
        self.setObjectName("StatCard")

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumWidth(160)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("StatTitle")
        self.title_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_row.addWidget(self.title_lbl)

        self.help_lbl = QLabel("ⓘ")
        self.help_lbl.setObjectName("HelpBadge")
        if tooltip:
            self.help_lbl.setToolTip(tooltip)
        self.help_lbl.setAlignment(Qt.AlignCenter)
        self.help_lbl.setFixedSize(18, 18)
        self.help_lbl.setCursor(QCursor(Qt.PointingHandCursor))
        header_row.addWidget(self.help_lbl)
        header_row.addStretch(1)

        outer.addLayout(header_row)

        self.value_lbl = QLabel(value)
        self.value_lbl.setObjectName("StatValue")
        self.value_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.value_lbl.setMinimumWidth(0)
        self.value_lbl.setWordWrap(True)
        outer.addWidget(self.value_lbl)

        self.subtitle_lbl = QLabel(subtitle)
        self.subtitle_lbl.setObjectName("StatSubtitle")
        self.subtitle_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.subtitle_lbl.setWordWrap(True)
        self.subtitle_lbl.setMinimumWidth(0)
        outer.addWidget(self.subtitle_lbl)

    def set_value(self, text: str):
        self.value_lbl.setText(text)

    def set_subtitle(self, text: str):
        self.subtitle_lbl.setText(text)


class NumericItem(QTableWidgetItem):


    def __init__(self, display: str, value: float):
        super().__init__(display)
        self.value = float(value)
        self.setData(Qt.UserRole, self.value)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self.value < other.value
        return super().__lt__(other)


class MplCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure(figsize=(5, 3), tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SCStats - v0.3")
        self.resize(1200, 700)

        font = self.font()
        font.setPointSize(9)
        self.setFont(font)

        self.current_thread: Optional[AnalyzerThread] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to logbackup folder...")
        browse_btn = QPushButton("Browse")
        self.calc_btn = QPushButton("Calculate")
        top.addWidget(self.path_edit, stretch=1)
        top.addWidget(browse_btn)
        top.addWidget(self.calc_btn)
        root.addLayout(top)

        prog_row = QHBoxLayout()
        self.progress_label = QLabel("Idle.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        prog_row.addWidget(self.progress_label)
        prog_row.addWidget(self.progress_bar)
        root.addLayout(prog_row)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        sessions_tab = QWidget()
        dash_layout = QVBoxLayout(sessions_tab)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.card_total = StatCard(
            "Total playtime",
            "-",
            "",
            "Sum of all valid session durations across every log. Sessions without a valid start/end timestamp are skipped.",
        )
        self.card_sessions = StatCard(
            "Sessions",
            "-",
            "",
            "Number of logs where we found a valid start and end timestamp.",
        )
        self.card_days = StatCard(
            "Days active",
            "-",
            "",
            "Unique calendar days that had at least one valid session.",
        )
        self.card_most = StatCard(
            "Most played version",
            "-",
            "",
            "Normalized version with the most total playtime.",
        )
        row1.addWidget(self.card_total)
        row1.addWidget(self.card_sessions)
        row1.addWidget(self.card_days)
        row1.addWidget(self.card_most)
        dash_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.card_avg_session = StatCard(
            "Avg session",
            "-",
            "",
            "Total playtime divided by number of sessions.",
        )
        self.card_avg_day = StatCard(
            "Avg per day",
            "-",
            "",
            "Total playtime divided by number of days with activity.",
        )
        self.card_longest_day = StatCard(
            "Most played day",
            "-",
            "",
            "Day with the highest accumulated playtime.",
        )
        self.card_gap = StatCard(
            "Biggest gap",
            "-",
            "",
            "Longest break between the end of one session and the start of the next.",
        )
        row2.addWidget(self.card_avg_session)
        row2.addWidget(self.card_avg_day)
        row2.addWidget(self.card_longest_day)
        row2.addWidget(self.card_gap)
        dash_layout.addLayout(row2)

        self.session_tables_tab = QTabWidget()

        version_tab = QWidget()
        v_layout = QVBoxLayout(version_tab)
        v_layout.setContentsMargins(0, 0, 0, 0)
        version_frame = QFrame()
        version_frame.setObjectName("TableFrame")
        vf_layout = QVBoxLayout(version_frame)
        vf_layout.setContentsMargins(8, 8, 8, 8)
        vf_layout.setSpacing(4)
        version_title = QLabel("Playtime per version (grouped):")
        version_title.setObjectName("TableTitle")
        vf_layout.addWidget(version_title)
        self.version_table = QTableWidget(0, 4)
        self.version_table.setHorizontalHeaderLabels(
            ["Version", "Hours", "Earliest", "Latest"]
        )
        self.version_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.version_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        vheader = self.version_table.horizontalHeader()
        vheader.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        vheader.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        vheader.setSectionResizeMode(2, QHeaderView.Stretch)
        vheader.setSectionResizeMode(3, QHeaderView.Stretch)
        self.version_table.setSortingEnabled(True)
        vf_layout.addWidget(self.version_table)
        v_layout.addWidget(version_frame)
        self.session_tables_tab.addTab(version_tab, "Versions")

        daily_tab = QWidget()
        d_layout = QVBoxLayout(daily_tab)
        d_layout.setContentsMargins(0, 0, 0, 0)

        daily_frame = QFrame()
        daily_frame.setObjectName("TableFrame")
        df_layout = QVBoxLayout(daily_frame)
        df_layout.setContentsMargins(8, 8, 8, 8)
        df_layout.setSpacing(4)
        daily_title = QLabel("Playtime per day (hours):")
        daily_title.setObjectName("TableTitle")
        df_layout.addWidget(daily_title)

        self.sessions_canvas = MplCanvas()
        df_layout.addWidget(self.sessions_canvas)
        d_layout.addWidget(daily_frame)
        self.session_tables_tab.addTab(daily_tab, "Daily Playtime")


        dash_layout.addWidget(self.session_tables_tab, stretch=1)

        self.tabs.addTab(sessions_tab, "Sessions")


        spending_tab = QWidget()
        spend_layout = QVBoxLayout(spending_tab)
        spend_layout.setContentsMargins(0, 0, 0, 0)
        spend_layout.setSpacing(8)

        srow1 = QHBoxLayout()
        srow1.setSpacing(8)
        self.sp_card_total_spent = StatCard(
            "Total spent",
            "-",
            "",
            "Total amount spent across all logged shop purchases.",
        )
        self.sp_card_purchases = StatCard(
            "Total purchases",
            "-",
            "",
            "Number of individual shop buy requests.",
        )
        self.sp_card_sessions = StatCard(
            "Sessions w/ purchases",
            "-",
            "",
            "How many log files contained at least one purchase.",
        )
        self.sp_card_shops = StatCard(
            "Distinct shops",
            "-",
            "",
            "Unique shop names you have bought from.",
        )
        srow1.addWidget(self.sp_card_total_spent)
        srow1.addWidget(self.sp_card_purchases)
        srow1.addWidget(self.sp_card_sessions)
        srow1.addWidget(self.sp_card_shops)
        spend_layout.addLayout(srow1)

        srow2 = QHBoxLayout()
        srow2.setSpacing(8)
        self.sp_card_avg_session = StatCard(
            "Avg per purchase session",
            "-",
            "",
            "Average money spent per session that contains at least one purchase.",
        )
        self.sp_card_first = StatCard(
            "First purchase",
            "-",
            "",
            "Time, shop and item of the earliest logged purchase.",
        )
        self.sp_card_last = StatCard(
            "Last purchase",
            "-",
            "",
            "Time, shop and item of the most recent logged purchase.",
        )
        self.sp_card_max_purchase = StatCard(
            "Most expensive purchase",
            "-",
            "",
            "Single shop buy request with the highest total cost (price * quantity).",
        )
        srow2.addWidget(self.sp_card_avg_session)
        srow2.addWidget(self.sp_card_first)
        srow2.addWidget(self.sp_card_last)
        srow2.addWidget(self.sp_card_max_purchase)
        spend_layout.addLayout(srow2)

        srow3 = QHBoxLayout()
        srow3.setSpacing(8)
        self.sp_card_max_session = StatCard(
            "Most expensive session",
            "-",
            "",
            "Session (log file) with the highest total spending.",
        )
        srow3.addWidget(self.sp_card_max_session)
        srow3.addStretch(1)
        spend_layout.addLayout(srow3)


        self.sp_tables_tab = QTabWidget()


        shops_tab = QWidget()
        shops_layout = QVBoxLayout(shops_tab)
        shops_layout.setContentsMargins(0, 0, 0, 0)
        shop_frame = QFrame()
        shop_frame.setObjectName("TableFrame")
        shop_frame_layout = QVBoxLayout(shop_frame)
        shop_frame_layout.setContentsMargins(8, 8, 8, 8)
        shop_frame_layout.setSpacing(4)
        shop_title = QLabel("Shops:")
        shop_title.setObjectName("TableTitle")
        shop_frame_layout.addWidget(shop_title)
        self.shop_table = QTableWidget(0, 3)
        self.shop_table.setHorizontalHeaderLabels(["Shop", "Transactions", "Spent"])
        self.shop_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.shop_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        sh_header = self.shop_table.horizontalHeader()
        sh_header.setSectionResizeMode(QHeaderView.Stretch)
        self.shop_table.setSortingEnabled(True)
        shop_frame_layout.addWidget(self.shop_table)
        shops_layout.addWidget(shop_frame)
        self.sp_tables_tab.addTab(shops_tab, "Shops")


        items_tab = QWidget()
        items_layout = QVBoxLayout(items_tab)
        items_layout.setContentsMargins(0, 0, 0, 0)
        item_frame = QFrame()
        item_frame.setObjectName("TableFrame")
        item_frame_layout = QVBoxLayout(item_frame)
        item_frame_layout.setContentsMargins(8, 8, 8, 8)
        item_frame_layout.setSpacing(4)
        item_title = QLabel("Items:")
        item_title.setObjectName("TableTitle")
        item_frame_layout.addWidget(item_title)
        self.item_table = QTableWidget(0, 3)
        self.item_table.setHorizontalHeaderLabels(["Item", "Transactions", "Spent"])
        self.item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        it_header = self.item_table.horizontalHeader()
        it_header.setSectionResizeMode(QHeaderView.Stretch)
        self.item_table.setSortingEnabled(True)
        item_frame_layout.addWidget(self.item_table)
        items_layout.addWidget(item_frame)
        self.sp_tables_tab.addTab(items_tab, "Items")

        spend_layout.addWidget(self.sp_tables_tab, stretch=1)

        self.tabs.addTab(spending_tab, "Spending")


        combat_tab = QWidget()
        combat_layout = QVBoxLayout(combat_tab)
        combat_layout.setContentsMargins(0, 0, 0, 0)
        combat_layout.setSpacing(8)

        crow1 = QHBoxLayout()
        crow1.setSpacing(8)
        self.cb_card_kills = StatCard(
            "Total kills",
            "-",
            "",
            "Total kills across all logs (players + NPCs).",
        )
        self.cb_card_deaths = StatCard(
            "Total deaths",
            "-",
            "",
            "Total times you died across all logs.",
        )
        self.cb_card_kd = StatCard(
            "K/D ratio",
            "-",
            "",
            "Kills divided by deaths. If deaths = 0, equals total kills.",
        )
        self.cb_card_kph = StatCard(
            "Kills per hour",
            "-",
            "",
            "Kills divided by total recorded playtime hours.",
        )
        crow1.addWidget(self.cb_card_kills)
        crow1.addWidget(self.cb_card_deaths)
        crow1.addWidget(self.cb_card_kd)
        crow1.addWidget(self.cb_card_kph)
        combat_layout.addLayout(crow1)

        crow2 = QHBoxLayout()
        crow2.setSpacing(8)
        self.cb_card_streak = StatCard(
            "Max kill streak",
            "-",
            "",
            "Highest number of consecutive kills without dying.",
        )
        self.cb_card_life = StatCard(
            "Avg time to death",
            "-",
            "",
            "Average time from session start to each death.",
        )
        self.cb_card_rage = StatCard(
            "Ragequits",
            "-",
            "",
            "Deaths followed by quitting within 10 seconds.",
        )
        self.cb_card_best_session = StatCard(
            "Best session (kills)",
            "-",
            "",
            "Session (log file) with the most total kills.",
        )
        crow2.addWidget(self.cb_card_streak)
        crow2.addWidget(self.cb_card_life)
        crow2.addWidget(self.cb_card_rage)
        crow2.addWidget(self.cb_card_best_session)
        combat_layout.addLayout(crow2)


        self.cb_tables_tab = QTabWidget()


        timeline_tab = QWidget()
        timeline_layout = QVBoxLayout(timeline_tab)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_frame = QFrame()
        timeline_frame.setObjectName("TableFrame")
        timeline_frame_layout = QVBoxLayout(timeline_frame)
        timeline_frame_layout.setContentsMargins(8, 8, 8, 8)
        timeline_frame_layout.setSpacing(4)
        tl_title = QLabel("Kills & deaths over time:")
        tl_title.setObjectName("TableTitle")
        timeline_frame_layout.addWidget(tl_title)
        self.combat_canvas = MplCanvas()
        timeline_frame_layout.addWidget(self.combat_canvas)
        timeline_layout.addWidget(timeline_frame)
        self.cb_tables_tab.addTab(timeline_tab, "Timeline")


        nemesis_tab = QWidget()
        nemesis_layout = QVBoxLayout(nemesis_tab)
        nemesis_layout.setContentsMargins(0, 0, 0, 0)
        nem_frame = QFrame()
        nem_frame.setObjectName("TableFrame")
        nem_frame_layout = QVBoxLayout(nem_frame)
        nem_frame_layout.setContentsMargins(8, 8, 8, 8)
        nem_frame_layout.setSpacing(4)
        nem_title = QLabel("Nemesis (players/NPCs who killed you):")
        nem_title.setObjectName("TableTitle")
        nem_frame_layout.addWidget(nem_title)
        self.cb_nemesis_table = QTableWidget(0, 2)
        self.cb_nemesis_table.setHorizontalHeaderLabels(["Name", "Times killed you"])
        self.cb_nemesis_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cb_nemesis_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        nem_header = self.cb_nemesis_table.horizontalHeader()
        nem_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cb_nemesis_table.setSortingEnabled(True)
        nem_frame_layout.addWidget(self.cb_nemesis_table)
        nemesis_layout.addWidget(nem_frame)
        self.cb_tables_tab.addTab(nemesis_tab, "Nemesis")


        victims_tab = QWidget()
        victims_layout = QVBoxLayout(victims_tab)
        victims_layout.setContentsMargins(0, 0, 0, 0)
        vic_frame = QFrame()
        vic_frame.setObjectName("TableFrame")
        vic_frame_layout = QVBoxLayout(vic_frame)
        vic_frame_layout.setContentsMargins(8, 8, 8, 8)
        vic_frame_layout.setSpacing(4)
        vic_title = QLabel("Victims (players/NPCs    you killed):")
        vic_title.setObjectName("TableTitle")
        vic_frame_layout.addWidget(vic_title)
        self.cb_victims_table = QTableWidget(0, 2)
        self.cb_victims_table.setHorizontalHeaderLabels(["Name", "Times you killed"])
        self.cb_victims_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cb_victims_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        vic_header = self.cb_victims_table.horizontalHeader()
        vic_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cb_victims_table.setSortingEnabled(True)
        vic_frame_layout.addWidget(self.cb_victims_table)
        victims_layout.addWidget(vic_frame)
        self.cb_tables_tab.addTab(victims_tab, "Victims")


        weapons_tab = QWidget()
        weapons_layout = QVBoxLayout(weapons_tab)
        weapons_layout.setContentsMargins(0, 0, 0, 0)
        wep_frame = QFrame()
        wep_frame.setObjectName("TableFrame")
        wep_frame_layout = QVBoxLayout(wep_frame)
        wep_frame_layout.setContentsMargins(8, 8, 8, 8)
        wep_frame_layout.setSpacing(4)
        wep_title = QLabel("Kills by weapon:")
        wep_title.setObjectName("TableTitle")
        wep_frame_layout.addWidget(wep_title)
        self.cb_weapons_table = QTableWidget(0, 2)
        self.cb_weapons_table.setHorizontalHeaderLabels(["Weapon", "Kills"])
        self.cb_weapons_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cb_weapons_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        wep_header = self.cb_weapons_table.horizontalHeader()
        wep_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cb_weapons_table.setSortingEnabled(True)
        wep_frame_layout.addWidget(self.cb_weapons_table)
        weapons_layout.addWidget(wep_frame)
        self.cb_tables_tab.addTab(weapons_tab, "Weapons")


        dtype_tab = QWidget()
        dtype_layout = QVBoxLayout(dtype_tab)
        dtype_layout.setContentsMargins(0, 0, 0, 0)
        dt_frame = QFrame()
        dt_frame.setObjectName("TableFrame")
        dt_frame_layout = QVBoxLayout(dt_frame)
        dt_frame_layout.setContentsMargins(8, 8, 8, 8)
        dt_frame_layout.setSpacing(4)
        dt_title = QLabel("Damage types YOU died to:")
        dt_title.setObjectName("TableTitle")
        dt_frame_layout.addWidget(dt_title)
        self.cb_dtype_table = QTableWidget(0, 2)
        self.cb_dtype_table.setHorizontalHeaderLabels(["Damage type", "Deaths"])
        self.cb_dtype_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cb_dtype_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        dt_header = self.cb_dtype_table.horizontalHeader()
        dt_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cb_dtype_table.setSortingEnabled(True)
        dt_frame_layout.addWidget(self.cb_dtype_table)
        dtype_layout.addWidget(dt_frame)
        self.cb_tables_tab.addTab(dtype_tab, "Damage types")


        npc_tab = QWidget()
        npc_layout = QVBoxLayout(npc_tab)
        npc_layout.setContentsMargins(0, 0, 0, 0)
        npc_frame = QFrame()
        npc_frame.setObjectName("TableFrame")
        npc_frame_layout = QVBoxLayout(npc_frame)
        npc_frame_layout.setContentsMargins(8, 8, 8, 8)
        npc_frame_layout.setSpacing(4)
        npc_title = QLabel("NPCs you killed (grouped):")
        npc_title.setObjectName("TableTitle")
        npc_frame_layout.addWidget(npc_title)
        self.cb_npc_table = QTableWidget(0, 2)
        self.cb_npc_table.setHorizontalHeaderLabels(["NPC type", "Kills"])
        self.cb_npc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cb_npc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        npc_header = self.cb_npc_table.horizontalHeader()
        npc_header.setSectionResizeMode(QHeaderView.Stretch)
        self.cb_npc_table.setSortingEnabled(True)
        npc_frame_layout.addWidget(self.cb_npc_table)
        npc_layout.addWidget(npc_frame)
        self.cb_tables_tab.addTab(npc_tab, "NPCs")

        combat_layout.addWidget(self.cb_tables_tab, stretch=1)

        self.tabs.addTab(combat_tab, "Combat")







        other_tab = QWidget()
        other_layout = QVBoxLayout(other_tab)
        other_layout.setContentsMargins(0, 0, 0, 0)
        other_layout.setSpacing(8)


        orow1 = QHBoxLayout()
        orow1.setSpacing(8)

        self.other_card_span = StatCard(
            "Log span",
            "-",
            "",
            "Coverage of all logs (difference between earliest and latest log timestamp)",
        )
        self.other_card_files = StatCard(
            "Total log files",
            "-",
            "",
            "Total number of log files processed",
        )
        self.other_card_total_lines = StatCard(
            "Total lines in log files",
            "-",
            "",
            "Total number of lines across all log files",
        )
        self.other_card_claims = StatCard(
            "Insurance claims",
            "-",
            "",
            "Number of insurance claim requests processed",
        )
        orow1.addWidget(self.other_card_span)
        orow1.addWidget(self.other_card_files)
        orow1.addWidget(self.other_card_total_lines)
        orow1.addWidget(self.other_card_claims)
        other_layout.addLayout(orow1)


        other_table_frame = QFrame()
        other_table_frame.setObjectName("TableFrame")
        ot_layout = QVBoxLayout(other_table_frame)
        ot_layout.setContentsMargins(8, 8, 8, 8)
        ot_layout.setSpacing(4)
        ot_title = QLabel("Mission completions:")
        ot_title.setObjectName("TableTitle")
        ot_layout.addWidget(ot_title)
        self.other_table = QTableWidget(0, 2)
        self.other_table.setHorizontalHeaderLabels(["Completion type", "Count"])
        self.other_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.other_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        oth_header = self.other_table.horizontalHeader()
        oth_header.setSectionResizeMode(QHeaderView.Stretch)
        self.other_table.setSortingEnabled(True)
        ot_layout.addWidget(self.other_table)
        other_layout.addWidget(other_table_frame, stretch=1)


        self.tabs.addTab(other_tab, "Other")






        export_tab = QWidget()
        export_layout = QVBoxLayout(export_tab)
        export_layout.setContentsMargins(10, 10, 10, 10)
        export_layout.setSpacing(12)


        desc_label = QLabel(
            "Export the data returned by SCStats to a JSON file. The exported file will contain "
            "all of the statistics computed from your log backups."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(
            "font-size: 10pt;"
            "color: #94a3b8;"
        )
        export_layout.addWidget(desc_label)


        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.setCursor(QCursor(Qt.PointingHandCursor))

        self.export_json_button.setFixedWidth(160)
        self.export_json_button.clicked.connect(self._export_json)

        export_layout.addWidget(self.export_json_button, alignment=Qt.AlignLeft)


        export_layout.addStretch(1)

        self.tabs.addTab(export_tab, "Export")






        socials_tab = QWidget()
        socials_layout = QVBoxLayout(socials_tab)
        socials_layout.setContentsMargins(10, 10, 10, 10)
        socials_layout.setSpacing(12)


        socials_heading = QLabel("Socials & Credits")
        socials_heading.setStyleSheet(
            "font-size: 18pt;"
            "font-weight: bold;"
            "color: #e2e8f0;"
        )
        socials_layout.addWidget(socials_heading)


        desc_html = (
            "<span>If you find <strong>SCStats</strong> helpful or have questions, we'd love to hear from you. "
            "Join our community on <a style='color:#3b82f6;' href='https://discord.com/invite/hxus8QJq56'>Discord</a> "
            "to share feedback, discuss features, or just hang out with fellow Star Citizen players.</span><br><br>"
            "<span>On our <a style='color:#3b82f6;' href='https://www.youtube.com/@rmap_'>YouTube channel</a> "
            "you'll find gameplay videos and highlights created with our organisation as well as other random clips. "
            "It's not directly related to SCStats, but you might still enjoy it.</span>"
        )
        socials_desc = QLabel()
        socials_desc.setText(desc_html)
        socials_desc.setOpenExternalLinks(True)
        socials_desc.setWordWrap(True)
        socials_desc.setStyleSheet(
            "font-size: 12pt;"
            "color: #cbd5e1;"
        )
        socials_layout.addWidget(socials_desc)


        credits_heading = QLabel("Credits")
        credits_heading.setStyleSheet(
            "margin-top: 24px;"
            "font-size: 14pt;"
            "font-weight: bold;"
            "color: #e2e8f0;"
        )
        socials_layout.addWidget(credits_heading)


        credits_details = QLabel(
            "Developer: RingledMaple\n"
            "Logo Design: G-rom"
        )
        credits_details.setStyleSheet(
            "font-size: 12pt;"
            "color: #cbd5e1;"
        )
        socials_layout.addWidget(credits_details)


        socials_layout.addStretch(1)

        self.tabs.addTab(socials_tab, "Socials && Credits")


        browse_btn.clicked.connect(self.browse_folder)
        self.calc_btn.clicked.connect(self.start_calc)

        self.path_edit.editingFinished.connect(self._on_path_changed)


        self.force_navy_palette()
        self.apply_navy_styles()


        self._load_settings()


        if not getattr(self, "_dont_remind_state", False):
            self._show_disclaimer()

    def force_navy_palette(self):
        pal = QPalette()
        bg = QColor("#0f172a")
        card = QColor("#111827")
        text = QColor("#ffffff")
        pal.setColor(QPalette.Window, bg)
        pal.setColor(QPalette.Base, card)
        pal.setColor(QPalette.AlternateBase, card)
        pal.setColor(QPalette.Button, QColor("#1f2937"))
        pal.setColor(QPalette.ButtonText, text)
        pal.setColor(QPalette.Text, text)
        pal.setColor(QPalette.WindowText, text)
        pal.setColor(QPalette.ToolTipBase, QColor("#1f2937"))
        pal.setColor(QPalette.ToolTipText, text)
        self.setPalette(pal)

    def apply_navy_styles(self):
        self.setStyleSheet(
            """
            QWidget {
                background: #0f172a;
                color: #ffffff;
            }
            QLineEdit {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 6px;
                padding: 4px 6px;
                color: #ffffff;
            }
            QPushButton {
                background: #1f2937;
                border: 1px solid #27354a;
                border-radius: 6px;
                padding: 4px 10px;
                color: #ffffff;
            }
            QPushButton:hover {
                background: #243047;
            }
            QTabWidget::pane {
                border: none;
            }
            QTabBar::tab {
                background: transparent;
                padding: 4px 10px;
                color: #d1d5db;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                border-bottom: 2px solid #38bdf8;
            }
            QFrame#StatCard {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 10px;
            }
            QFrame#StatCard QLabel {
                background: transparent;
            }
            QLabel#StatTitle {
                font-size: 10px;
                color: #94a3b8;
            }
            QLabel#StatValue {
                font-size: 18px;
                font-weight: 600;
                color: #ffffff;
            }
            QLabel#StatSubtitle {
                font-size: 10px;
                color: #cbd5f5;
            }
            QLabel#HelpBadge {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 9px;
                font-size: 10px;
                color: #ffffff;
            }
            QFrame#TableFrame {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 10px;
            }
            QLabel#TableTitle {
                color: #e2e8f0;
                font-weight: 600;
            }
            QTableWidget {
                background: #111827;
                color: #ffffff;
                gridline-color: #1f2937;
                selection-background-color: #1f2937;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background: #0f172a;
                color: #e2e8f0;
                border: none;
                padding: 4px;
            }
            QScrollArea {
                background: transparent;
            }
            QProgressBar {
                background: #1f2937;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background: #38bdf8;
                border-radius: 5px;
            }
        """
        )


    def _show_disclaimer(self) -> None:
        """
        Display a modal-like overlay that darkens the background and presents
        a professional disclaimer message to the user. The overlay consists of
        a semi‑transparent full‑window widget with a centered panel containing
        the disclaimer text, a “Don’t remind me again” checkbox, and a
        randomized acknowledgement button. The pop‑up is designed to occupy
        more screen real estate and uses a red colour scheme for emphasis.

        This method should only be called once during initialization.
        """
        """
        Create and display the disclaimer overlay.  The overlay covers the
        entire window with a semi‑transparent dark layer, then centers a
        dark dialog box containing red disclaimer text, a “Don’t remind me
        again” checkbox, and a non‑red acknowledgement button.  The dialog
        adapts to window size and is sized to roughly 70 % of the window
        width (capped at 900 px) and automatically sized for height.
        """

        self._disclaimer_overlay = QWidget(self)
        self._disclaimer_overlay.setObjectName("DisclaimerOverlay")
        self._disclaimer_overlay.setStyleSheet(
            "#DisclaimerOverlay { background-color: rgba(0, 0, 0, 160); }"
        )
        self._disclaimer_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._disclaimer_overlay.setGeometry(self.rect())
        self._disclaimer_overlay.show()
        self._disclaimer_overlay.raise_()


        popup = QFrame(self._disclaimer_overlay)
        popup.setObjectName("DisclaimerPopup")
        popup.setStyleSheet(
            "#DisclaimerPopup {"
            " background-color: #111827;"
            " border-radius: 12px;"
            " padding: 32px;"
            "}"
        )


        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(24, 24, 24, 24)
        popup_layout.setSpacing(20)


        title_label = QLabel("DISCLAIMER", popup)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            "font-size: 22pt;"
            "font-weight: bold;"
            "color: #D22B2B;"
        )
        popup_layout.addWidget(title_label)


        body_text = (
            "SCStats analyzes Star Citizen log files stored in your “logbackups” folder. "
            "All statistics displayed (playtime, spending, combat, missions, etc.) are calculated only from the sessions "
            "present in those logs.\n\n"
            "Because Star Citizen’s logging format and behaviour have changed over time, the results shown here should be considered "
            "an approximation of your overall history, not an official or complete record."
        )
        body_label = QLabel(body_text, popup)
        body_label.setWordWrap(True)
        body_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        body_label.setStyleSheet(
            "font-size: 11pt;"
            "line-height: 1.5em;"
            "color: #ffffff;"
        )
        popup_layout.addWidget(body_label)


        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(12)


        self._dont_remind_checkbox = QCheckBox("Don't remind me again", popup)
        self._dont_remind_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 11pt;
                color: #ffffff;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #ffffff;
                background: transparent;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #ffffff;
                background: #D22B2B;
            }
            """
        )

        self._dont_remind_checkbox.toggled.connect(self._on_dont_remind_changed)
        bottom_row.addWidget(self._dont_remind_checkbox)
        bottom_row.addStretch(1)



        btn_text_options = ["OK", "I understand", "Got it", "Continue"]
        ack_button = QPushButton(random.choice(btn_text_options), popup)
        ack_button.setCursor(QCursor(Qt.PointingHandCursor))
        ack_button.setStyleSheet(
            "QPushButton {"
            " background-color: #1f2937;"
            " border: 2px solid #D22B2B;"
            " color: #D22B2B;"
            " padding: 10px 20px;"
            " border-radius: 6px;"
            " font-size: 12pt;"
            "}"
            "QPushButton:hover {"
            " background-color: #243047;"
            "}"
        )
        ack_button.clicked.connect(self._dismiss_disclaimer)
        bottom_row.addWidget(ack_button)
        popup_layout.addLayout(bottom_row)


        popup_width = min(900, int(self.width() * 0.7))
        popup.setFixedWidth(popup_width)
        popup.adjustSize()


        popup_x = (self.width() - popup.width()) // 2
        popup_y = (self.height() - popup.height()) // 2
        popup.move(popup_x, popup_y)

    def _dismiss_disclaimer(self) -> None:
        """Hide and clean up the disclaimer overlay when acknowledged."""
        if hasattr(self, "_disclaimer_overlay") and self._disclaimer_overlay:
            self._disclaimer_overlay.hide()
            self._disclaimer_overlay.deleteLater()
            self._disclaimer_overlay = None

    def resizeEvent(self, event: QEvent) -> None:
        """
        Reimplement the resize event to ensure the disclaimer overlay and its
        content remain properly sized and positioned when the main window is
        resized. This override maintains the original resize behavior and
        supplements it with overlay adjustments.
        """

        super().resizeEvent(event)

        if hasattr(self, "_disclaimer_overlay") and self._disclaimer_overlay:

            self._disclaimer_overlay.setGeometry(self.rect())

            popup = self._disclaimer_overlay.findChild(QFrame, "DisclaimerPopup")
            if popup is not None:

                new_width = min(900, int(self.width() * 0.7))
                popup.setFixedWidth(new_width)
                popup.adjustSize()
                new_x = (self.width() - popup.width()) // 2
                new_y = (self.height() - popup.height()) // 2
                popup.move(new_x, new_y)


    def _set_table_item(self, table: QTableWidget, row: int, col: int, text: Any):
        item = QTableWidgetItem(str(text))
        item.setForeground(QColor("#ffffff"))
        table.setItem(row, col, item)

    def _set_numeric_item(
        self,
        table: QTableWidget,
        row: int,
        col: int,
        display: str,
        value: float,
    ):
        item = NumericItem(display, value)
        item.setForeground(QColor("#ffffff"))
        table.setItem(row, col, item)











    def _get_config_dirs(self) -> Tuple[Optional[Path], Path]:
        """
        Return candidate directories for storing configuration files.

        The first preference is a subdirectory named ``scstats`` under
        the user's application data directory (typically given by
        ``%APPDATA%`` on Windows).  The second preference is an
        ``scstats`` subdirectory in the directory containing this script.

        Returns a tuple ``(appdata_dir, root_dir)`` where ``appdata_dir``
        may be ``None`` if no application data directory is defined.
        """
        appdata_env = os.environ.get("APPDATA")
        appdata_dir: Optional[Path] = None
        if appdata_env:
            appdata_dir = Path(appdata_env) / "scstats"
        root_dir: Path = Path(__file__).resolve().parent / "scstats"
        return appdata_dir, root_dir

    def _load_settings(self) -> None:
        """
        Load persisted settings from configuration file, if present.

        This will attempt to read ``config.json`` from the candidate
        directories returned by :meth:`_get_config_dirs` in order of
        preference.  On success, the saved log path is applied to
        ``self.path_edit`` and the ``_dont_remind_state`` flag is set
        according to the stored value.  If no configuration is found or
        readable, defaults are used.
        """

        self._dont_remind_state: bool = False

        appdata_dir, root_dir = self._get_config_dirs()
        config_dirs: List[Path] = []
        if appdata_dir is not None:
            config_dirs.append(appdata_dir)
        config_dirs.append(root_dir)
        for d in config_dirs:
            config_path = d / "config.json"
            if config_path.exists():
                try:
                    with config_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)

                    saved_path = data.get("log_path")
                    if saved_path:
                        self.path_edit.setText(str(saved_path))

                    self._dont_remind_state = bool(data.get("dont_remind"))

                    self._config_dir_used = d
                    return
                except Exception:

                    pass

        if appdata_dir is not None:
            self._config_dir_used = appdata_dir
        else:
            self._config_dir_used = root_dir

    def _save_settings(self) -> None:
        """
        Persist current settings to a JSON file.

        The method writes a ``config.json`` containing the current log
        path and disclaimer preference.  It first attempts to write to
        the user's application data directory; if that fails, it falls
        back to the program directory.  If writing fails for both
        locations, no exception is raised and the settings are not saved.
        """
        data = {
            "log_path": self.path_edit.text().strip(),
            "dont_remind": bool(getattr(self, "_dont_remind_state", False)),
        }

        appdata_dir, root_dir = self._get_config_dirs()
        for target_dir in [appdata_dir, root_dir]:
            if target_dir is None:
                continue
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                config_path = target_dir / "config.json"
                with config_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                self._config_dir_used = target_dir
                return
            except Exception:
                continue

        pass

    def _on_path_changed(self) -> None:
        """Persist the log path when the user finishes editing."""

        self._save_settings()

    def _on_dont_remind_changed(self, state: bool) -> None:
        """Persist the disclaimer preference when the checkbox is toggled."""
        self._dont_remind_state = bool(state)
        self._save_settings()

    def _export_json(self) -> None:
        """
        Prompt the user for a file path and save the most recent
        statistics dictionary as JSON.  If no statistics have been
        computed yet, the method does nothing.  Uses a QFileDialog
        configured for saving JSON files and writes using ``json.dump``.
        """


        if getattr(self, "current_thread", None) is not None and self.current_thread.isRunning():
            QMessageBox.information(
                self,
                "Processing",
                "Please wait for processing to finish before exporting."
            )
            return
        stats = getattr(self, "last_stats", None)
        if not stats:

            QMessageBox.information(
                self,
                "No data to export",
                "Please select your logbackup folder and calculate the statistics before exporting."
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            "stats.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
        except Exception:

            pass


    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select logbackup folder")
        if folder:
            self.path_edit.setText(folder)

            self._on_path_changed()

    def start_calc(self):
        folder = self.path_edit.text().strip()
        if not folder:
            self.progress_label.setText("Select a folder first.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Preparing…")
        self.calc_btn.setEnabled(False)

        self.current_thread = AnalyzerThread(folder)
        self.current_thread.progress.connect(self._on_progress)
        self.current_thread.finished_ok.connect(self._on_finished)
        self.current_thread.failed.connect(self._on_failed)
        self.current_thread.start()

    def _on_progress(self, current: int, total: int):
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"Parsing logs… {current}/{total}")

    def _on_finished(self, stats: dict):
        self.calc_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Done.")
        self.populate_dashboard(stats)
        self.populate_spending(stats.get("spending", {}))
        self.populate_combat(stats.get("combat", {}))
        self.populate_other(stats.get("other", {}))

        self.last_stats = stats

    def _on_failed(self, msg: str):
        self.calc_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        self.progress_label.setText(f"Error: {msg}")

    def populate_dashboard(self, stats: dict):
        self.card_total.set_value(f"{stats['total_seconds'] / 3600:.2f}h")
        self.card_total.set_subtitle(f"Skipped logs: {stats['malformed']}")

        self.card_sessions.set_value(str(stats["sessions"]))
        self.card_sessions.set_subtitle("Valid sessions parsed")

        self.card_days.set_value(str(stats["days_played"]))
        self.card_days.set_subtitle("Unique days with activity")

        if stats.get("most_played"):
            mp = stats["most_played"]
            self.card_most.set_value(mp["version"])
            self.card_most.set_subtitle(f"{mp['seconds'] / 3600:.2f}h")
        else:
            self.card_most.set_value("-")
            self.card_most.set_subtitle("")

        self.card_avg_session.set_value(f"{stats['average_seconds'] / 3600:.2f}h")
        self.card_avg_day.set_value(
            f"{stats['average_per_day_seconds'] / 3600:.2f}h"
        )

        if stats.get("longest_day"):
            ld = stats["longest_day"]
            self.card_longest_day.set_value(ld["day"])
            self.card_longest_day.set_subtitle(f"{ld['seconds'] / 3600:.2f}h")
        else:
            self.card_longest_day.set_value("-")
            self.card_longest_day.set_subtitle("")

        if stats.get("biggest_gap"):
            bg = stats["biggest_gap"]
            days = bg["seconds"] / 86400
            self.card_gap.set_value(f"{days:.2f} d")
            self.card_gap.set_subtitle(
                f"{format_ts_str(bg['from'])} -> {format_ts_str(bg['to'])}"
            )
        else:
            self.card_gap.set_value("-")
            self.card_gap.set_subtitle("")

        pv = stats["per_version"]

        sorting = self.version_table.isSortingEnabled()
        self.version_table.setSortingEnabled(False)

        self.version_table.setRowCount(len(pv))
        for row, (ver, info) in enumerate(sorted(pv.items())):
            hrs = info["seconds"] / 3600
            self._set_table_item(self.version_table, row, 0, ver)
            self._set_numeric_item(self.version_table, row, 1, f"{hrs:.2f}", hrs)
            self._set_table_item(
                self.version_table, row, 2, format_ts_str(info["earliest"])
            )
            self._set_table_item(
                self.version_table, row, 3, format_ts_str(info["latest"])
            )

        self.version_table.setSortingEnabled(sorting)



        self._plot_daily_playtime(stats.get("day_totals", {}))

    def populate_spending(self, stats: dict):
        if not stats or stats.get("total_purchases", 0) == 0:
            self.sp_card_total_spent.set_value("-")
            self.sp_card_total_spent.set_subtitle("")
            self.sp_card_purchases.set_value("0")
            self.sp_card_purchases.set_subtitle("")
            self.sp_card_sessions.set_value("0")
            self.sp_card_sessions.set_subtitle("")
            self.sp_card_shops.set_value("0")
            self.sp_card_shops.set_subtitle("")
            self.sp_card_avg_session.set_value("-")
            self.sp_card_avg_session.set_subtitle("")
            self.sp_card_first.set_value("-")
            self.sp_card_first.set_subtitle("")
            self.sp_card_last.set_value("-")
            self.sp_card_last.set_subtitle("")
            self.sp_card_max_purchase.set_value("-")
            self.sp_card_max_purchase.set_subtitle("")
            self.sp_card_max_session.set_value("-")
            self.sp_card_max_session.set_subtitle("")
            self.shop_table.setRowCount(0)
            self.item_table.setRowCount(0)
            return

        total_spent = stats["total_spent"]
        total_purchases = stats["total_purchases"]
        sessions_with_purchases = stats["sessions_with_purchases"]
        distinct_shops = stats["distinct_shops"]
        distinct_items = stats["distinct_items"]
        avg_spent_session = stats["average_spent_per_session"]

        self.sp_card_total_spent.set_value(format_human(total_spent))
        self.sp_card_total_spent.set_subtitle("Total money spent")

        self.sp_card_purchases.set_value(str(total_purchases))
        self.sp_card_purchases.set_subtitle("Total purchase events")

        self.sp_card_sessions.set_value(str(sessions_with_purchases))
        self.sp_card_sessions.set_subtitle("Sessions containing purchases")

        self.sp_card_shops.set_value(str(distinct_shops))
        self.sp_card_shops.set_subtitle(f"Distinct items: {distinct_items}")

        self.sp_card_avg_session.set_value(format_human(avg_spent_session))
        self.sp_card_avg_session.set_subtitle("Avg total spending per session")

        fp = stats.get("first_purchase")
        if fp:
            self.sp_card_first.set_value(format_ts_str(fp["time"]))
            self.sp_card_first.set_subtitle(
                f"{fp['shop']} · {fp['item']} ({format_human(fp['spent'])})"
            )
        else:
            self.sp_card_first.set_value("-")
            self.sp_card_first.set_subtitle("")

        lp = stats.get("last_purchase")
        if lp:
            self.sp_card_last.set_value(format_ts_str(lp["time"]))
            self.sp_card_last.set_subtitle(
                f"{lp['shop']} · {lp['item']} ({format_human(lp['spent'])})"
            )
        else:
            self.sp_card_last.set_value("-")
            self.sp_card_last.set_subtitle("")

        mp = stats.get("max_purchase")
        if mp:
            self.sp_card_max_purchase.set_value(format_human(mp["spent"]))

            self.sp_card_max_purchase.set_subtitle(mp["shop"])
        else:
            self.sp_card_max_purchase.set_value("-")
            self.sp_card_max_purchase.set_subtitle("")

        ms = stats.get("max_session")
        if ms:
            self.sp_card_max_session.set_value(format_human(ms["spent"]))

            ts = ms.get("time")
            date_str = "-"
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    date_str = dt.date().isoformat()
                except Exception:
                    date_str = ts
            self.sp_card_max_session.set_subtitle(date_str)
        else:
            self.sp_card_max_session.set_value("-")
            self.sp_card_max_session.set_subtitle("")


        shops = stats.get("shops", {})
        sorted_shops = sorted(
            shops.items(), key=lambda kv: (-kv[1]["spent"], -kv[1]["count"])
        )

        sorting_shops = self.shop_table.isSortingEnabled()
        self.shop_table.setSortingEnabled(False)

        self.shop_table.setRowCount(len(sorted_shops))
        for row, (shop_name, data) in enumerate(sorted_shops):
            self._set_table_item(self.shop_table, row, 0, shop_name)
            self._set_numeric_item(
                self.shop_table, row, 1, str(int(data["count"])), int(data["count"])
            )
            self._set_numeric_item(
                self.shop_table,
                row,
                2,
                format_human_with_unit(data["spent"]),
                data["spent"],
            )

        self.shop_table.setSortingEnabled(sorting_shops)


        items = stats.get("items", {})
        sorted_items = sorted(
            items.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["spent"])
        )

        sorting_items = self.item_table.isSortingEnabled()
        self.item_table.setSortingEnabled(False)

        self.item_table.setRowCount(len(sorted_items))
        for row, (item_name, data) in enumerate(sorted_items):
            self._set_table_item(self.item_table, row, 0, item_name)
            self._set_numeric_item(
                self.item_table, row, 1, str(int(data["count"])), int(data["count"])
            )
            self._set_numeric_item(
                self.item_table,
                row,
                2,
                format_human_with_unit(data["spent"]),
                data["spent"],
            )

        self.item_table.setSortingEnabled(sorting_items)

    def populate_combat(self, stats: dict):

        if not stats or (
            stats.get("total_kills", 0) == 0 and stats.get("total_deaths", 0) == 0
        ):
            self.cb_card_kills.set_value("-")
            self.cb_card_deaths.set_value("-")
            self.cb_card_kd.set_value("-")
            self.cb_card_kph.set_value("-")
            self.cb_card_streak.set_value("-")
            self.cb_card_life.set_value("-")
            self.cb_card_rage.set_value("-")
            self.cb_card_best_session.set_value("-")
            self.cb_card_kills.set_subtitle("")
            self.cb_card_deaths.set_subtitle("")
            self.cb_card_best_session.set_subtitle("")

            for tbl in [
                self.cb_nemesis_table,
                self.cb_victims_table,
                self.cb_weapons_table,
                self.cb_dtype_table,
                self.cb_npc_table,
            ]:
                tbl.setRowCount(0)

            self.combat_canvas.ax.clear()
            self.combat_canvas.ax.text(
                0.5,
                0.5,
                "No combat events detected",
                ha="center",
                va="center",
                transform=self.combat_canvas.ax.transAxes,
                color="white",
            )
            self.combat_canvas.draw()
            return

        total_kills = stats.get("total_kills", 0)
        total_deaths = stats.get("total_deaths", 0)
        kd = stats.get("kd_ratio", 0.0)
        kph = stats.get("kills_per_hour", 0.0)
        max_streak = stats.get("max_kill_streak", 0)
        ragequits = stats.get("ragequits", 0)
        suicides = stats.get("suicides", 0)
        avg_life_s = stats.get("overall_avg_life_seconds", None)
        best_session_kills = stats.get("best_session_kills", 0)
        best_session_file = stats.get("best_session_file", None)

        kills_vs_players = stats.get("kills_vs_players", 0)
        kills_vs_npcs = stats.get("kills_vs_npcs", 0)

        self.cb_card_kills.set_value(str(total_kills))
        self.cb_card_kills.set_subtitle(
            f"vs players: {kills_vs_players} · vs NPCs: {kills_vs_npcs}"
        )

        self.cb_card_deaths.set_value(str(total_deaths))
        self.cb_card_deaths.set_subtitle(f"Suicides: {suicides}")

        self.cb_card_kd.set_value(f"{kd:.2f}")
        self.cb_card_kd.set_subtitle("Overall across all logs")

        self.cb_card_kph.set_value(f"{kph:.3f}")
        self.cb_card_kph.set_subtitle("Kills per hour of recorded playtime")

        self.cb_card_streak.set_value(str(max_streak))
        self.cb_card_streak.set_subtitle("Best kill streak")

        if avg_life_s is not None:
            mins = avg_life_s / 60.0
            self.cb_card_life.set_value(f"{mins:.2f} min")
            self.cb_card_life.set_subtitle("Avg from session start to death")
        else:
            self.cb_card_life.set_value("-")
            self.cb_card_life.set_subtitle("No deaths detected")

        self.cb_card_rage.set_value(str(ragequits))
        self.cb_card_rage.set_subtitle("Deaths followed by quit < 10s")

        self.cb_card_best_session.set_value(str(best_session_kills))
        if best_session_file:
            self.cb_card_best_session.set_subtitle(best_session_file)
        else:
            self.cb_card_best_session.set_subtitle("")



        nemesis = stats.get("nemesis", [])
        sorting = self.cb_nemesis_table.isSortingEnabled()
        self.cb_nemesis_table.setSortingEnabled(False)
        self.cb_nemesis_table.setRowCount(len(nemesis))
        for row, (name, count) in enumerate(nemesis):
            self._set_table_item(self.cb_nemesis_table, row, 0, name)
            self._set_numeric_item(
                self.cb_nemesis_table, row, 1, str(int(count)), int(count)
            )
        self.cb_nemesis_table.setSortingEnabled(sorting)


        victims = stats.get("reverse_nemesis", [])
        sorting = self.cb_victims_table.isSortingEnabled()
        self.cb_victims_table.setSortingEnabled(False)
        self.cb_victims_table.setRowCount(len(victims))
        for row, (name, count) in enumerate(victims):
            self._set_table_item(self.cb_victims_table, row, 0, name)
            self._set_numeric_item(
                self.cb_victims_table, row, 1, str(int(count)), int(count)
            )
        self.cb_victims_table.setSortingEnabled(sorting)


        wep_dict = stats.get("kills_by_weapon", {})
        wep_sorted = sorted(wep_dict.items(), key=lambda x: x[1], reverse=True)
        sorting = self.cb_weapons_table.isSortingEnabled()
        self.cb_weapons_table.setSortingEnabled(False)
        self.cb_weapons_table.setRowCount(len(wep_sorted))
        for row, (weapon, count) in enumerate(wep_sorted):
            self._set_table_item(self.cb_weapons_table, row, 0, weapon)
            self._set_numeric_item(
                self.cb_weapons_table, row, 1, str(int(count)), int(count)
            )
        self.cb_weapons_table.setSortingEnabled(sorting)


        dt_dict = stats.get("deaths_by_damage_type", {})
        dt_sorted = sorted(dt_dict.items(), key=lambda x: x[1], reverse=True)
        sorting = self.cb_dtype_table.isSortingEnabled()
        self.cb_dtype_table.setSortingEnabled(False)
        self.cb_dtype_table.setRowCount(len(dt_sorted))
        for row, (dtype, count) in enumerate(dt_sorted):
            self._set_table_item(self.cb_dtype_table, row, 0, dtype)
            self._set_numeric_item(
                self.cb_dtype_table, row, 1, str(int(count)), int(count)
            )
        self.cb_dtype_table.setSortingEnabled(sorting)


        npc_dict = stats.get("npc_kills_by_type", {})
        npc_sorted = sorted(npc_dict.items(), key=lambda x: x[1], reverse=True)
        sorting = self.cb_npc_table.isSortingEnabled()
        self.cb_npc_table.setSortingEnabled(False)
        self.cb_npc_table.setRowCount(len(npc_sorted))
        for row, (npc_label, count) in enumerate(npc_sorted):
            self._set_table_item(self.cb_npc_table, row, 0, npc_label)
            self._set_numeric_item(
                self.cb_npc_table, row, 1, str(int(count)), int(count)
            )
        self.cb_npc_table.setSortingEnabled(sorting)


        self._plot_combat_timeline(
            stats.get("kill_timestamps", []), stats.get("death_timestamps", [])
        )

    def populate_other(self, stats: dict):
        """
        Populate the 'Other' tab with miscellaneous statistics.
        Shows overall log span, number of log files, total lines across logs,
        insurance claim requests and mission completion summary.
        """

        if not stats:
            for card in [
                self.other_card_span,
                self.other_card_files,
                self.other_card_total_lines,
                self.other_card_claims,
            ]:
                card.set_value("-")
                card.set_subtitle("")

            self.other_table.setRowCount(0)
            return


        span = stats.get("log_span")
        if span:
            self.other_card_span.set_value(span)

            self.other_card_span.set_subtitle("")
        else:
            self.other_card_span.set_value("-")
            self.other_card_span.set_subtitle("")


        total_files = stats.get("total_files", 0)
        malformed = stats.get("malformed", 0)
        self.other_card_files.set_value(str(total_files))
        self.other_card_files.set_subtitle(f"Malformed: {malformed}")


        total_lines = stats.get("total_lines", 0)
        self.other_card_total_lines.set_value(str(total_lines))
        self.other_card_total_lines.set_subtitle("lines")


        claims = stats.get("insurance_claims", 0)
        self.other_card_claims.set_value(str(claims))
        self.other_card_claims.set_subtitle("requests")


        m_counts = stats.get("mission_completion_counts", {})
        if not m_counts:
            self.other_table.setRowCount(0)
        else:
            items = sorted(m_counts.items(), key=lambda x: (-x[1], x[0]))
            self.other_table.setRowCount(len(items))
            self.other_table.setSortingEnabled(False)
            for row, (ctype, count) in enumerate(items):

                item_name = QTableWidgetItem(str(ctype))
                item_name.setForeground(QColor("#ffffff"))
                self.other_table.setItem(row, 0, item_name)

                num_item = NumericItem(str(int(count)), int(count))
                num_item.setForeground(QColor("#ffffff"))
                self.other_table.setItem(row, 1, num_item)
            self.other_table.setSortingEnabled(True)

    def _plot_daily_playtime(self, day_totals: Dict[str, int]):
        """
        Plot total playtime per day on the sessions canvas.
        Expects a dictionary mapping 'YYYY-MM-DD' to seconds of playtime.
        Days with no activity are simply omitted.
        """
        ax = self.sessions_canvas.ax
        ax.clear()
        if not day_totals:

            ax.text(
                0.5,
                0.5,
                "No playtime data",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="white",
            )
            self.sessions_canvas.draw()
            return


        from datetime import datetime as _dt
        try:
            parsed = [(_dt.fromisoformat(day), day) for day in day_totals.keys()]
            parsed.sort(key=lambda t: t[0])
            dates = [p[0] for p in parsed]
            keys_ordered = [p[1] for p in parsed]
        except Exception:

            keys_ordered = sorted(day_totals.keys())
            dates = keys_ordered


        y_vals = [day_totals[k] / 3600.0 for k in keys_ordered]


        ax.plot(dates, y_vals, marker="", linestyle="-", color="cyan")
        ax.set_xlabel("Date")
        ax.set_ylabel("Hours played")

        ax.set_facecolor("#111827")
        self.sessions_canvas.fig.patch.set_facecolor("#111827")

        if dates and hasattr(dates[0], 'isoformat'):
            self.sessions_canvas.fig.autofmt_xdate()

        for spine in ax.spines.values():
            spine.set_color("white")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")
        ax.grid(True, alpha=0.2, color="#334155")

        self.sessions_canvas.draw()





    def _plot_vehicle_timeline(self, events: List[Tuple[str, int]]):
        """(deprecated) Vehicle timeline plotting has been removed."""

        return

    def _plot_combat_timeline(
        self, kill_ts_strings: List[str], death_ts_strings: List[str]
    ):
        from datetime import datetime as _dt

        ax = self.combat_canvas.ax
        ax.clear()

        kill_ts = sorted(
            (_dt.fromisoformat(ts) for ts in kill_ts_strings), key=lambda d: d
        )
        death_ts = sorted(
            (_dt.fromisoformat(ts) for ts in death_ts_strings), key=lambda d: d
        )

        if not kill_ts and not death_ts:
            ax.text(
                0.5,
                0.5,
                "No combat events detected",
                ha="center",
                va="center",
                transform=ax.transAxes,
                color="white",
            )
            self.combat_canvas.draw()
            return


        ax.set_facecolor("#111827")
        self.combat_canvas.fig.patch.set_facecolor("#111827")

        if kill_ts:
            ax.plot(
                kill_ts,
                list(range(1, len(kill_ts) + 1)),
                label="Kills",
                color="red",
            )
        if death_ts:
            ax.plot(
                death_ts,
                list(range(1, len(death_ts) + 1)),
                label="Deaths",
                color="cyan",
            )

        ax.set_xlabel("Time")
        ax.set_ylabel("Cumulative count")

        for spine in ax.spines.values():
            spine.set_color("white")
        ax.tick_params(colors="white")
        ax.xaxis.label.set_color("white")
        ax.yaxis.label.set_color("white")

        ax.legend(facecolor="#111827", edgecolor="white", labelcolor="white")
        ax.grid(True, alpha=0.2, color="#334155")

        self.combat_canvas.fig.autofmt_xdate()
        self.combat_canvas.draw()


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)


    icon_path = resource_path("SCS_TOOL_ICON_SMALL.ico")
    app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    win.setWindowIcon(QIcon(icon_path))

    win.show()
    sys.exit(app.exec())



if __name__ == "__main__":
    main()
