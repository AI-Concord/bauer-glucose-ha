# Bauer Glucose (LibreLinkUp) for Home Assistant

A Home Assistant custom integration + Lovelace card for tracking a diabetic
pet's glucose via a FreeStyle Libre CGM, using the same LibreLinkUp
"follower" data your phone app already gets. Built for Bauer 🐾 — a
diabetic cat on a Libre 3 Plus sensor — but works for any Libre patient
shared to a LibreLinkUp follower account.

**This is not medical software.** Thresholds are configurable and default to
rough starting points only. Confirm target ranges and any dosing decisions
with your veterinarian.

## What this gets you

- **`sensor.<name>_glucose`** — current mg/dL reading, with trend arrow,
  rate of change, and a rolling history array (used by the card's graph;
  Home Assistant's own recorder also gives you long-term history/statistics
  on this entity automatically, no separate database needed).
- **`sensor.<name>_glucose_rate`** — rate of change in mg/dL/min.
- **`binary_sensor.<name>_rapid_change`** — on when glucose is moving faster
  than your configured rate threshold, in either direction.
- **`binary_sensor.<name>_out_of_range`** / **`..._urgent_range`** — on when
  outside the low/high band, and separately when in the *urgent* band.
- **`binary_sensor.<name>_stale_reading`** — on if no new reading has arrived
  in a while (sensor fell off, app not syncing, follower link broken).
- **`bauer_glucose_urgent_range`** / **`bauer_glucose_rapid_change`** —
  Home Assistant events you can automate on. An included blueprint wires
  these to a TTS announcement on your speakers (e.g. Google Nest) and an
  optional mobile push.
- **`bauer-glucose-card`** — a Lovelace tile: big colored number (green in
  range, amber near the edges, red urgent), trend arrow, badges, and an
  inline graph of recent readings.

## Architecture

```
Libre 3 Plus sensor  →  LibreLink app (primary account, on the caretaker's phone)
                              │  shares readings to a "follower"
                              ▼
                     LibreLinkUp follower account
                              │  polled every ~60s (unofficial API)
                              ▼
        custom_components/bauer_glucose  (this integration)
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
     HA sensors/binary   HA recorder      HA events on
     sensors (state +    (history/long-   rapid-change /
     attributes)         term stats,      urgent-range
                          free, no extra   (edge-triggered,
                          setup)           repeats ~10 min
                                           while ongoing)
                              │
                              ▼
                    automation blueprint
                    → tts.speak on Nest media_players
                    → optional mobile notify
```

No Nightscout, MQTT broker, or extra database required — LibreLinkUp is
polled directly, and Home Assistant's built-in recorder handles history
storage for the sensor entities.

### Why LibreLinkUp and not "the glucometer" directly

Abbott's Libre sensors don't expose a local API — the reader/phone talks to
Abbott's cloud. LibreLinkUp is Abbott's own "share with a caregiver" feature
and is the same mechanism every third-party Libre integration (Nightscout
uploaders, other HA integrations, etc.) uses. It's unofficial in the sense
that Abbott hasn't published it as a public API, so **it can break if Abbott
changes their app protocol** — see Troubleshooting below.

## Setup

### 1. Create a LibreLinkUp follower login

On the phone running the primary LibreLink/Libre 3 app (Bauer's actual
monitoring phone):

1. Open the LibreLinkUp companion app (or LibreLink → Settings → Sharing),
   and invite an email address as a follower — you can use your own email,
   just make sure it's a *separate* login from the primary account's
   password (LibreLinkUp lets you set your own password for the follower
   login).
2. Accept the invite from that email, and set a password for the follower
   account if you weren't prompted already.
3. Open the LibreLinkUp app **once** and log in with those credentials, and
   accept any Terms of Use prompt — the API will reject requests from an
   account that hasn't done this at least once.

Use *these* credentials in Home Assistant, not the primary account's.

### 2. Install the integration

Copy `custom_components/bauer_glucose/` into your Home Assistant `config/`
directory (so you end up with
`config/custom_components/bauer_glucose/manifest.json`), or add this repo
as a HACS custom repository (category: Integration) and install from there.
Restart Home Assistant.

Settings → Devices & Services → Add Integration → **Bauer Glucose
(LibreLinkUp)**. Enter the follower email/password and region, then pick the
patient if the account follows more than one.

After setup, open the integration's **Configure** button to set/adjust
thresholds (urgent low, low, high, urgent high, rapid-change rate, stale
timeout, poll interval — minimum 60s).

### 3. Install the card

Copy `www/bauer-glucose-card.js` into your HA `config/www/` directory, then
add it as a dashboard resource: Settings → Dashboards → ⋮ → Resources → Add
Resource, URL `/local/bauer-glucose-card.js`, type JavaScript Module. (HACS
install, if used, registers this automatically.)

See `docs/dashboard-example.yaml` for a full example view; minimal card
config:

```yaml
type: custom:bauer-glucose-card
entity: sensor.bauers_glucose_monitor_glucose
name: Bauer
hours: 3
```

### 4. Wire up announcements

Import `blueprints/automation/bauer_glucose/announce_alert.yaml`
(Settings → Automations → Blueprints → Import Blueprint, or drop the file
into `config/blueprints/automation/bauer_glucose/`), then create an
automation from it:

- **Announcement speakers** — your Google Nest `media_player` entities.
- **TTS entity** — whatever TTS engine you already have configured (e.g.
  `tts.google_translate_en_com`, or a cloud TTS integration).
- **Mobile notification targets** — optional, any `notify.*` entities for a
  push notification alongside the announcement.
- Toggle whether it reacts to urgent-range, rapid-change, or both.

The integration re-fires the alert event roughly every 10 minutes while the
condition persists, so the blueprint will keep re-announcing "still needs
checking" until glucose comes back into range — it doesn't just say it once
and go quiet.

## Tuning thresholds

Defaults (`const.py`) are ballpark figures, **not** vet guidance:

| Setting | Default |
|---|---|
| Urgent low | 60 mg/dL |
| Low | 80 mg/dL |
| High | 250 mg/dL |
| Urgent high | 350 mg/dL |
| Rapid change | 4 mg/dL/min sustained |
| Stale after | 20 minutes |

Change these in the integration's Options after setup to match your vet's
actual target range for Bauer.

## Troubleshooting

- **"Could not log in"** — double check you're using the *follower* login,
  not the primary LibreLink account. Open the LibreLinkUp app once on any
  phone with those credentials to clear any pending Terms-of-Use step.
- **Everything suddenly stops working** — Abbott occasionally bumps the
  minimum app version LibreLinkUp's backend accepts. Check
  `custom_components/bauer_glucose/api.py`'s `LLU_VERSION` constant against
  the current LibreLinkUp app version and bump it; this is the single most
  common breakage point for any unofficial Libre client.
- **`stale_reading` binary sensor stuck on** — usually means the phone
  running the primary LibreLink app hasn't synced recently (Bluetooth range,
  app not running, phone off). LibreLinkUp only sees what the primary app
  has uploaded.

## Disclaimer

Built for personal use monitoring a family pet's CGM data. Not affiliated
with Abbott. Not for human medical use, and not a substitute for veterinary
guidance on interpreting readings or making dosing decisions.
