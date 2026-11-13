# Hardware Integration Checklist (EVB Lite arrival day)

Print this page. Details for each step are in [`evb-lite-integration.md`](evb-lite-integration.md).

## A. Before you start
- [ ] App running: `docker compose up -d`, then open <http://localhost:8080>. Simulation works end to end.
- [ ] Sensor fully charged.
- [ ] EVident documentation and Device Hub downloaded; note their versions.
- [ ] Laptop on the same UniFi network/VLAN that the sensor will join.

## B. Network
- [ ] Sensor joined the private **2.4 GHz** SSID.
- [ ] IP and MAC noted from UniFi → Client Devices: `IP __________  MAC __________`
- [ ] **DHCP reservation / fixed IP** created in UniFi.
- [ ] **Client Device Isolation OFF** for that SSID.
- [ ] `ping <ip>` works from Windows.
- [ ] `curl.exe -i http://<ip>/` returns a page.
- [ ] From the container: `docker compose exec app python -c "import urllib.request as u; print(u.urlopen('http://<ip>/', timeout=5).status)"` → `200`.
- [ ] App: Operator → Sensor → address saved → **Run diagnostics** all green.

## C. Identify the device (fill in §3 of the integration doc)
- [ ] Model / hardware ID: __________   Firmware: __________
- [ ] Portal URL that works: __________   Login required? ____
- [ ] Documented API pages/endpoints (with doc reference): __________
- [ ] DevTools HAR saved to `docs/evb-lite-evidence/`

## D. Characterize the data
- [ ] Units (flat on table, vertical axis reads): ____ (g / mg / m/s²)
- [ ] Axis that reads +1 g when the lander is upright: ____ → `axis_map`
- [ ] Timestamp field / unit / epoch: __________
- [ ] Consecutive timestamps are distinct at full rate? ____
- [ ] Effective rate over 10 s: ______ Hz
- [ ] Live streaming or record-then-download? __________
- [ ] Clipping behaviour at ±16 g: __________
- [ ] Wi-Fi drop behaviour (gap or buffered?): __________
- [ ] Battery level available? where: __________

## E. Integrate
- [ ] Chose path: A polling / B record + import / C streaming / D Device Hub export only
- [ ] (Path A) `config/evb_profile.json` filled in with **verified** values, `source_of_truth` cited
- [ ] Operator → Sensor → **Reload EVB profile** → mode **EVB Lite** → "live capture ready"
- [ ] (Path B/D) Practised: record → download CSV → Operator → Data → **Import CSV** (origin: Physical)

## F. Acceptance tests (§7 of the integration doc)
- [ ] Static 1 g, six faces
- [ ] Observed rate within ±2 % of the expected rate; completeness ≥ 99 %
- [ ] 5 foam drops at 10 cm → all valid with free fall detected
- [ ] Handling the armed lander does not trigger
- [ ] Over-range rigid drop flagged and excluded
- [ ] Wi-Fi off while armed → clear error, UI usable, auto-reconnect
- [ ] Sensor power cycle → app reconnects
- [ ] Export ZIP contains raw responses

## G. Physical station
- [ ] Sensor rigidly mounted in the payload bay (no foam tape)
- [ ] Each built lander weighed; masses entered (Operator → Landing gear)
- [ ] Only the built presets enabled
- [ ] Drop heights students can choose give valid results below ±16 g (include 10 cm); listed in Operator → Station
- [ ] Same landing surface for every drop
- [ ] A release method that drops straight down without a push
