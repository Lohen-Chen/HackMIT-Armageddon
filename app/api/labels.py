"""Human-readable names for panel feature columns (used by the drivers panel)."""
import re

CAMEO_ROOT = {
    "10": "demands", "11": "disapproval", "12": "rejections", "13": "threats", "14": "protests",
    "15": "shows of force", "16": "reduced relations", "17": "coercion", "18": "assaults",
    "19": "fighting", "20": "mass violence",
}
WINDOW = {"w1": "last week", "w4": "last 4 wks", "w13": "last 13 wks", "w52": "last 52 wks"}
BASE = {
    "n_events": "event volume", "n_mentions": "media mentions", "n_root": "root events",
    "q1": "verbal cooperation", "q2": "material cooperation", "q3": "verbal conflict",
    "q4": "material conflict", "q4_m": "material-conflict mentions",
    "goldstein_sum": "Goldstein total", "goldstein_wsum": "mention-weighted Goldstein total",
    "tone_sum": "tone total", "tone_wsum": "mention-weighted tone total",
    "goldstein_mean": "avg Goldstein (hostility)", "goldstein_wmean": "weighted avg Goldstein",
    "tone_mean": "avg media tone", "tone_wmean": "weighted avg tone",
    "q4_share": "material-conflict share", "q3_share": "verbal-conflict share",
    "q1_share": "verbal-cooperation share", "conflict_share": "conflict share of events",
    "q4_mention_share": "conflict share of mentions", "root_share": "root-event share",
    "rate": "share of global GDELT volume", "q4_rate": "conflict share of global volume",
    "q4_ab": "material conflict A→B", "q4_ba": "material conflict B→A", "q4_asym": "conflict asymmetry",
    "q4_base_4w": "trailing 4-wk conflict baseline",
    "ev_ratio_1_13": "event surge (1 wk vs 13 wk)", "ev_ratio_4_52": "event surge (4 wk vs 52 wk)",
    "q4_ratio_1_13": "conflict surge (1 wk vs 13 wk)", "q4_ratio_4_52": "conflict surge (4 wk vs 52 wk)",
    "goldstein_delta_1_13": "Goldstein shift (1 vs 13 wk)", "goldstein_delta_4_52": "Goldstein shift (4 vs 52 wk)",
    "tone_delta_4_52": "tone shift (4 vs 52 wk)",
    "icb_prior_crises": "prior ICB crises (this dyad)", "days_since_icb_onset": "days since last ICB onset",
    "regime_daily": "GDELT daily-file era",
}


def feature_label(col: str) -> str:
    if col in BASE:
        return BASE[col]
    m = re.match(r"^(r|m)(\d\d)(_share)?_(w\d+)$", col)
    if m:
        kind, root, share, w = m.groups()
        base = CAMEO_ROOT.get(root, f"CAMEO {root}")
        what = f"{base} ({'mentions' if kind == 'm' else 'events'})"
        return f"{'share of ' if share else ''}{what}, {WINDOW.get(w, w)}"
    m = re.match(r"^(.*)_(w\d+)$", col)
    if m:
        base, w = m.groups()
        return f"{BASE.get(base, base)}, {WINDOW.get(w, w)}"
    return col.replace("_", " ")
