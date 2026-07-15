# Email Draft — PACE/AAM Brand Feed Request

**To:** [PACE/AAM rep]
**From:** Titan Truck Equipment
**Subject:** Brand feed additions + AAIA cross-reference questions

---

Hi [Rep],

We're rebuilding the Titan Truck Equipment website using your PACE ACES + PIES feeds, and we have a few asks based on cross-referencing our parts master against what we've already received from you.

## 1. Additional brand feeds we'd like to receive

These brands carry stock at Titan but we don't currently get PACE feeds for them. Each one's AAIA brand ID per our cross-reference (`dci_codes`):

| Titan prod_code | AAIA code | Brand | Active SKUs in our catalog |
|---|---|---|---|
| SKY | BHNG | Skyjacker | 6,405 |
| PUT | FKLF | Putco | 5,852 |
| STA | BHPC | Stampede | 5,719 |
| BAJA | FGXX | Baja Designs | 3,495 |
| ANZ | ZUKT | Anzo | 2,511 |
| T-REX | DJTM | T-Rex Grilles | 2,166 |
| NFA | BKES | N-Fab | 2,031 |
| FFI | DKSN | Fab Fours | 1,728 |
| ARD | BGPQ | Airaid | 1,635 |
| ALS | BGPT | All Sales | 1,618 |
| WAR | BCSQ | Warn Industries | brand row exists; 0 SKUs ingested (need PIES) |

## 2. Brand verification — Weatherguard / Knaack

Our `dci_codes` table maps our internal prod_code **KNK** (Weatherguard) to AAIA brand **DKJD**. However, the Weatherguard PIES feed we received from you has BrandAAIAID **HWZD** (with parts like 96312-3-01 "Full Bulkhead Screen").

**Question:** Is the correct AAIA code for Weatherguard HWZD or DKJD? Are these two different brands, or is our cross-reference table out of date?

## 3. Confirming missing brands aren't available

We understand from prior conversations that these are **not** in the AAM Group line — please confirm so we know to source elsewhere:

- ECCO (emergency lighting, ~2,000 SKUs)
- Federal Signal (emergency lighting, ~7,000 SKUs)
- Buyers Products (general truck equipment, ~12,000 SKUs)
- Bilstein (suspension shocks, ~4,500 SKUs)
- 3D MaxPider (floor mats, ~3,700 SKUs)
- Nitro Gear & Axle (drivetrain, ~3,500 SKUs)

If any of these ARE actually available through PACE under a brand code we missed, please let us know.

## 4. AAIA code lookups

We have a number of prod_codes in our internal master that aren't in our `dci_codes` cross-reference. Could you let us know if AAIA brand IDs exist for any of these?

- HOFF (Hoffman Group) — we don't sell this on the public site, just need to confirm
- ORL, RRK, BIL, 3DU, NITRO, TUFF, LTP, KST, ROAD, TFP

## 5. Buyers Products feed

We believe a Buyers Products PACE feed was downloaded recently but we can't locate it on our side. Could you confirm whether it was actually delivered, and if so, the file name/timestamp so we can track it down?

---

Thanks,
Titan Truck Equipment
