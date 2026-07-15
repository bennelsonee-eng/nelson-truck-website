# Redundant facet-key audit

- Leaf categories with >=2 facet-eligible numeric keys: **58**
- Raw pairs above overlap threshold: **354**
  - LABEL_VARIANT (safe auto-merge, name differs only by format): **57**
  - SYNONYM_CANDIDATE (needs curator confirm): **158**
  - LIKELY_FALSE (coincidental small ints / years, ignore): **139**
- **Merge clusters (connected components of real pairs): 50**
- Distinct categories affected: **27**
- Thresholds: jaccard >= 0.4, min-products >= 5, numeric-frac >= 0.6
- Scope: leaf categories only (direct membership). Roll-up-node-only redundancies are not counted.

## Merge clusters (the real sizing)

- **[SYNONYM]** `Cable Diameter`  ·  `Diameter`  ·  `Diameter (IN)`  ·  `Height`  ·  `Height (in.)`  ·  `Hub Bore Diameter`  ·  `Inside Diameter`  ·  `Item Height`  ·  `Line Diameter (IN)`  ·  `Rim Diameter`  ·  `SideStep Size`  ·  `SideStep Size (in.)`  ·  `Step Pad Surface Width`  ·  `Surface Width`  ·  `Wheel Width`
- **[SYNONYM]** `Gross Trailer Weight`  ·  `Gross Trailer Weight (GTW)`  ·  `Gross Trailer Weight (lbs.)`  ·  `Gross Trailer Weight(GTW)`  ·  `Maximum Gross Trailer Weight`  ·  `Weight Carrying Capacity`  ·  `Weight Carrying Capacity (WC)`  ·  `Weight Carrying Capacity(WC)`  ·  `Weight Distribution`  ·  `Weight Distribution (WD)`  ·  `Weight Distribution(WD)`
- **[SYNONYM]** `Face Size`  ·  `LED Number`  ·  `LED Quantity`  ·  `LEDs`  ·  `Length`  ·  `Length (in.)`  ·  `Length (mm)`  ·  `Light Bar Length`  ·  `Overall Length`  ·  `Overall Length (in.)`
- **[SYNONYM]** `Front Flare Height`  ·  `Front Flare Height (inches)`  ·  `Front Flare Tire Coverage`  ·  `Front Flare Tire Coverage (inches)`  ·  `Rear Flare Height`  ·  `Rear Flare Height (inches)`  ·  `Rear Flare Tire Coverage`  ·  `Rear Flare Tire Coverage (inches)`
- **[SYNONYM]** `Maximum Tongue Weight`  ·  `Tongue Weight (TW)`  ·  `Tongue Weight(TW)`  ·  `WC Tongue Weight`  ·  `WD Tongue Weight`  ·  `Weight Distribution Tongue Weight (WDTW)`  ·  `Weight Distribution Tongue Weight(WDTW)`
- **[SYNONYM]** `Air Filter Oulet Length`  ·  `Air Filter Oulet Width`  ·  `Air Filter Outlet Length`  ·  `Air Filter Outlet Width`  ·  `Intake Pipe Inlet Length`  ·  `Intake Pipe Inlet Width`  ·  `Intake Pipe Outlet Length`
- **[SYNONYM]** `Front Lift Height`  ·  `Lift Height`  ·  `Lift/Drop Height`  ·  `Lift/Drop Height (in.)`  ·  `Lift_Height`  ·  `Maximum Lift`  ·  `Rear Lift Height`
- **[SYNONYM]** `Ball Mount Drop`  ·  `Drop (in)`  ·  `Drop Measurement`  ·  `Drop/Raise Range`  ·  `Rise (in)`  ·  `Rise Measurement`
- **[SYNONYM]** `Bed Rail Length`  ·  `Length (FT)`  ·  `Line Length`  ·  `Line Length (FT)`  ·  `Product Length`
- **[SYNONYM]** `Gallon Capacity`  ·  `Liquid Storage Capacity`  ·  `Volume`  ·  `WEB: Box Width/Tank Capacity`
- **[SYNONYM]** `Rated Line Pull`  ·  `Rated Single Line Pull (lbs.)`  ·  `Rating`  ·  `Winch Rating`
- **[SYNONYM]** `Rim Width`  ·  `Wheel Diameter`  ·  `Width`  ·  `Width (in.)`
- **[SYNONYM]** `Lower Mount Type`  ·  `Lower Mounting Description`  ·  `Upper Mount Type`  ·  `Upper Mounting Description`
- **[SYNONYM]** `Lower Mount Code`  ·  `Lower Mounting Code`  ·  `Upper Mount Code`  ·  `Upper Mounting Code`
- **[SYNONYM]** `Power Consumption`  ·  `Wattage`  ·  `Watts`
- **[SYNONYM]** `Avg Install time`  ·  `Install Time`  ·  `Installation Time`
- **[SYNONYM]** `Product Line`  ·  `Style`  ·  `Sub-category (Line)`
- **[SYNONYM]** `Motor Voltage`  ·  `Voltage`  ·  `Volts`
- **[SYNONYM]** `Collapsed Length`  ·  `Collapsed Length (in.)`  ·  `Compressed Length`
- **[SYNONYM]** `Body Diameter`  ·  `Cylinder Outside Diameter`  ·  `Reserve Tube Diameter`
- **[SYNONYM]** `Extended Length`  ·  `Extended Length (in.)`  ·  `Fully Open Length`
- **[SYNONYM]** `Shock Stroke`  ·  `Shock Stroke (in.)`  ·  `Travel Length`
- **[SYNONYM]** `Receiver Size (in)`  ·  `Shank Size`  ·  `Shank Size (in)`
- **[SYNONYM]** `Carb/Air Horn Dia. (in.)`  ·  `CARB/Air Horn Diameter`  ·  `CARB/Air Horn Diameter (in.)`
- **[SYNONYM]** `Ball Mount Drop Load Capacity`  ·  `Gross Towing Weight`  ·  `Towing Capacity`
- **[label-variant]** `Total Length`  ·  `TOTAL LENGTH`
- **[SYNONYM]** `Inlet Diameter`  ·  `Neck Flange`
- **[SYNONYM]** `Breaking Strength (LB)`  ·  `Capacity`
- **[SYNONYM]** `Amp Draw per Bulb`  ·  `Amperage Rating`
- **[label-variant]** `Line Diameter`  ·  `Pin Diameter`
- **[label-variant]** `Avg Install Time`  ·  `Avg. Install Time`
- **[SYNONYM]** `Base Outside Width`  ·  `Top Outside Width`
- **[SYNONYM]** `Package Quantity`  ·  `This Product Includes`
- **[label-variant]** `Body Length`  ·  `Body Length (in.)`
- **[SYNONYM]** `Offset`  ·  `Positive Offset`
- **[SYNONYM]** `Item Weight`  ·  `Weight`
- **[SYNONYM]** `Tire Info`  ·  `Tire Information`
- **[SYNONYM]** `Tail Light Circuits`  ·  `Turn and Brake Circuits`
- **[SYNONYM]** `Weight Capacity`  ·  `Work Load Limit`
- **[SYNONYM]** `Amp Draw`  ·  `Amperage Draw`
- **[SYNONYM]** `Full Pallet Qty`  ·  `Full Pallet Quantity`
- **[SYNONYM]** `Receiver Size`  ·  `Receiver Tube Size`
- **[SYNONYM]** `Front Flare Width`  ·  `Rear Flare Width`
- **[label-variant]** `Max Year Covered`  ·  `Min Year Covered`
- **[label-variant]** `Parts Pack`  ·  `Parts Pack(s)`
- **[label-variant]** `Board Length`  ·  `Board Length (in.)`
- **[SYNONYM]** `Front Shocks`  ·  `Rear Shocks`
- **[label-variant]** `Bar Diameter`  ·  `Bar Diameter (in.)`
- **[SYNONYM]** `Air Filter Large End Diameter`  ·  `Base Outside Diameter`
- **[SYNONYM]** `Base Outside Length`  ·  `Top Outside Length`

## SYNONYM_CANDIDATE - needs curator  (158)

### `Install Time`  vs  `Installation Time`
- categories: **13**  ·  peak reach: **1963**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "Less than 1 hour"  /  "1 hour"
    - `1 / 2`  ->  "1-2 hours"  /  "1-2 hours"
    - `2 / 3`  ->  "2-3 hours"  /  "2-3 hours"
    - `3 / 4`  ->  "3-4 hours"  /  "3-4 hours"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights; Truck Accessories > Exterior > Fender Liners and Accessories; Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Leveling Kits; Truck Equipment > Winches and Accessories; Truck Accessories > Bumpers and Grille Guards > Front Bumpers; Truck Accessories > Cargo Management > Cargo Racks; Truck Accessories > Cargo Management > Truck and Van Racks  (+5 more)

### `Body Diameter`  vs  `Reserve Tube Diameter`
- categories: **3**  ·  peak reach: **435**  ·  mean jaccard: 0.78  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2.13`  ->  "2.13"  /  "2.13"
    - `2`  ->  "2"  /  "2.000 in."
    - `2.129`  ->  "2.129"  /  "2.129"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Lift Height`  vs  `Lift/Drop Height`
- categories: **2**  ·  peak reach: **1139**  ·  mean jaccard: 0.42  ·  max containment: 0.89
- shared values (sig -> forms):
    - `2`  ->  "2 in"  /  "2 in."
    - `0.75`  ->  "0.75"  /  "0.75 in."
    - `3`  ->  "3"  /  "3 in."
    - `2.5`  ->  "2.5 in"  /  "2.5 in."
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Lift/Drop Height`  vs  `Maximum Lift`
- categories: **2**  ·  peak reach: **1117**  ·  mean jaccard: 0.46  ·  max containment: 0.89
- shared values (sig -> forms):
    - `2`  ->  "2 in."  /  "2 Inch"
    - `0.75`  ->  "0.75 in."  /  "0.75"
    - `3`  ->  "3 in."  /  "3"
    - `2.5`  ->  "2.5 in."  /  "2.5 Inch"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Style`  vs  `Sub-category (Line)`
- categories: **2**  ·  peak reach: **725**  ·  mean jaccard: 0.51  ·  max containment: 1.00
- shared values (sig -> forms):
    - `10`  ->  "RB10"  /  "RB10 Running boards"
    - `20`  ->  "RB20"  /  "RB20 Running boards"
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Step Bars

### `Shock Stroke`  vs  `Travel Length`
- categories: **2**  ·  peak reach: **532**  ·  mean jaccard: 0.56  ·  max containment: 0.99
- shared values (sig -> forms):
    - `8.01`  ->  "8.010 in."  /  "8.01"
    - `10.13`  ->  "10.130 in."  /  "10.13"
    - `202.7`  ->  "202.7"  /  "202.7"
    - `5.87`  ->  "5.870 in."  /  "5.87"
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Lift Height`  vs  `Lift/Drop Height (in.)`
- categories: **2**  ·  peak reach: **467**  ·  mean jaccard: 0.47  ·  max containment: 0.81
- shared values (sig -> forms):
    - `2`  ->  "2 in"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `2.5`  ->  "2.5 in"  /  "2.5"
    - `1.5`  ->  "1.5"  /  "1.5"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Lift/Drop Height (in.)`  vs  `Maximum Lift`
- categories: **2**  ·  peak reach: **445**  ·  mean jaccard: 0.55  ·  max containment: 0.89
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 Inch"
    - `3`  ->  "3"  /  "3"
    - `2.5`  ->  "2.5"  /  "2.5 Inch"
    - `1.5`  ->  "1.5"  /  "1.5"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Front Lift Height`  vs  `Lift/Drop Height (in.)`
- categories: **2**  ·  peak reach: **341**  ·  mean jaccard: 0.47  ·  max containment: 0.86
- shared values (sig -> forms):
    - `2`  ->  "2 Inches"  /  "2"
    - `3`  ->  "3 Inches"  /  "3"
    - `2.5`  ->  "2.5 Inches"  /  "2.5"
    - `1.5`  ->  "1.5 Inches"  /  "1.5"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Lift Height`  vs  `Maximum Lift`
- categories: **2**  ·  peak reach: **338**  ·  mean jaccard: 0.62  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2 in"  /  "2 Inch"
    - `0.75`  ->  "0.75"  /  "0.75"
    - `3`  ->  "3"  /  "3"
    - `2.5`  ->  "2.5 in"  /  "2.5 Inch"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Collapsed Length`  vs  `Compressed Length`
- categories: **2**  ·  peak reach: **306**  ·  mean jaccard: 0.43  ·  max containment: 0.67
- shared values (sig -> forms):
    - `11.29`  ->  "11.29"  /  "11.290"
    - `13.73`  ->  "13.73"  /  "13.730"
    - `16.6`  ->  "16.6"  /  "16.6"
    - `15.98`  ->  "15.98"  /  "15.98"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories

### `Upper Mount Type`  vs  `Upper Mounting Description`
- categories: **2**  ·  peak reach: **298**  ·  mean jaccard: 0.63  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.5 / 8`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
    - `5 / 8 / 16 / 1.1 / 2`  ->  "Loop Bushing and Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"
    - `12 / 1.1 / 4`  ->  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Shock Stroke (in.)`  vs  `Travel Length`
- categories: **2**  ·  peak reach: **280**  ·  mean jaccard: 0.50  ·  max containment: 0.97
- shared values (sig -> forms):
    - `8.01`  ->  "8.010"  /  "8.01"
    - `10.13`  ->  "10.130"  /  "10.13"
    - `5.87`  ->  "5.870"  /  "5.87"
    - `11.07`  ->  "11.070"  /  "11.07"
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Collapsed Length (in.)`  vs  `Compressed Length`
- categories: **2**  ·  peak reach: **270**  ·  mean jaccard: 0.46  ·  max containment: 1.00
- shared values (sig -> forms):
    - `11.29`  ->  "11.290"  /  "11.290"
    - `13.73`  ->  "13.730"  /  "13.730"
    - `15.98`  ->  "15.980"  /  "15.98"
    - `13.98`  ->  "13.980"  /  "13.980"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories

### `Front Lift Height`  vs  `Maximum Lift`
- categories: **2**  ·  peak reach: **212**  ·  mean jaccard: 0.55  ·  max containment: 0.86
- shared values (sig -> forms):
    - `2`  ->  "2 Inches"  /  "2 Inch"
    - `3`  ->  "3 Inches"  /  "3"
    - `2.5`  ->  "2.5 Inches"  /  "2.5 Inch"
    - `1.5`  ->  "1.5 Inches"  /  "1.5"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Extended Length`  vs  `Fully Open Length`
- categories: **2**  ·  peak reach: **212**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `23.89`  ->  "23.89"  /  "23.890 in."
    - `24.68`  ->  "24.680 in."  /  "24.680 in."
    - `32.29`  ->  "32.29"  /  "32.290 in."
    - `18.7`  ->  "18.7"  /  "18.700 in."
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Extended Length (in.)`  vs  `Fully Open Length`
- categories: **2**  ·  peak reach: **62**  ·  mean jaccard: 0.88  ·  max containment: 1.00
- shared values (sig -> forms):
    - `23.89`  ->  "23.890 in."  /  "23.890 in."
    - `24.68`  ->  "24.680 in."  /  "24.680 in."
    - `32.29`  ->  "32.290 in."  /  "32.290 in."
    - `18.7`  ->  "18.700 in."  /  "18.700 in."
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Gallon Capacity`  vs  `Volume`
- categories: **2**  ·  peak reach: **42**  ·  mean jaccard: 0.52  ·  max containment: 0.70
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50 Gallons"
    - `60`  ->  "60"  /  "60 Gallons"
    - `100`  ->  "100"  /  "100 Gallons"
    - `12`  ->  "12"  /  "12 Gallons"
- in: Truck Accessories > Transfer Tanks; Truck Equipment > Transfer Tanks

### `Amp Draw per Bulb`  vs  `Amperage Rating`
- categories: **2**  ·  peak reach: **41**  ·  mean jaccard: 0.57  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1.3 / 13`  ->  "1.3 Amps @ 13V DC"  /  "1.3 Amps @ 13V DC"
    - `2.4 / 13`  ->  "2.4 Amps @ 13V DC"  /  "2.4 Amps @ 13V DC"
    - `10.6 / 13`  ->  "10.6 Amps @ 13V DC"  /  "10.6 Amps @ 13V DC"
    - `8.8 / 13`  ->  "8.8 Amps @ 13V DC"  /  "8.8 Amps @ 13V DC"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights; Truck Accessories > Automotive Lighting > LED Headlight Conversion Kits

### `Volume`  vs  `WEB: Box Width/Tank Capacity`
- categories: **2**  ·  peak reach: **37**  ·  mean jaccard: 0.40  ·  max containment: 0.71
- shared values (sig -> forms):
    - `50`  ->  "50 Gallons"  /  "50 Gallon"
    - `100`  ->  "100 Gallons"  /  "100 Gallon"
    - `55`  ->  "55 Gallons"  /  "55 Gallon"
    - `80`  ->  "80 Gallons"  /  "80 Gallon"
- in: Truck Accessories > Transfer Tanks; Truck Equipment > Transfer Tanks

### `Liquid Storage Capacity`  vs  `Volume`
- categories: **2**  ·  peak reach: **31**  ·  mean jaccard: 0.41  ·  max containment: 0.90
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50 Gallons"
    - `55`  ->  "55"  /  "55 Gallons"
    - `92`  ->  "92"  /  "92 Gallons"
    - `80`  ->  "80"  /  "80 Gallons"
- in: Truck Accessories > Transfer Tanks; Truck Equipment > Transfer Tanks

### `Liquid Storage Capacity`  vs  `WEB: Box Width/Tank Capacity`
- categories: **2**  ·  peak reach: **18**  ·  mean jaccard: 0.50  ·  max containment: 0.80
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50 Gallon"
    - `55`  ->  "55"  /  "55 Gallon"
    - `92`  ->  "92"  /  "92 Gallon"
    - `80`  ->  "80"  /  "80 Gallon"
- in: Truck Accessories > Transfer Tanks; Truck Equipment > Transfer Tanks

### `Tongue Weight(TW)`  vs  `Weight Distribution Tongue Weight(WDTW)`
- categories: **1**  ·  peak reach: **4344**  ·  mean jaccard: 0.40  ·  max containment: 0.71
- shared values (sig -> forms):
    - `500`  ->  "500 LB"  /  "500 LB"
    - `400`  ->  "400 LB"  /  "400 LB"
    - `2550`  ->  "2,550 LB"  /  "2,550 LB"
    - `900`  ->  "900 LB"  /  "900 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `WC Tongue Weight`  vs  `Weight Distribution Tongue Weight(WDTW)`
- categories: **1**  ·  peak reach: **4305**  ·  mean jaccard: 0.40  ·  max containment: 0.71
- shared values (sig -> forms):
    - `500`  ->  "500"  /  "500 LB"
    - `400`  ->  "400"  /  "400 LB"
    - `2550`  ->  "2550"  /  "2,550 LB"
    - `900`  ->  "900"  /  "900 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **4260**  ·  mean jaccard: 0.41  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17,000 LB"
    - `12000`  ->  "12000 lbs."  /  "12,000 LB"
    - `18000`  ->  "18000 lbs."  /  "18,000 LB"
    - `8000`  ->  "8000 lbs."  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **4248**  ·  mean jaccard: 0.41  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LB"
    - `18000`  ->  "18000"  /  "18,000 LB"
    - `8000`  ->  "8000"  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity(WC)`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **4219**  ·  mean jaccard: 0.46  ·  max containment: 0.67
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `12000`  ->  "12,000 LB"  /  "12,000 LB"
    - `18000`  ->  "18,000 LB"  /  "18,000 LB"
    - `8000`  ->  "8,000 LB"  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **4199**  ·  mean jaccard: 0.46  ·  max containment: 0.67
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LB"
    - `18000`  ->  "18000"  /  "18,000 LB"
    - `8000`  ->  "8000"  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity (WC)`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **3456**  ·  mean jaccard: 0.46  ·  max containment: 0.67
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `12000`  ->  "12,000 LBS"  /  "12,000 LB"
    - `18000`  ->  "18,000 LB"  /  "18,000 LB"
    - `8000`  ->  "8,000 LBS"  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight(TW)`  vs  `Weight Distribution Tongue Weight (WDTW)`
- categories: **1**  ·  peak reach: **3339**  ·  mean jaccard: 0.44  ·  max containment: 0.67
- shared values (sig -> forms):
    - `500`  ->  "500 LB"  /  "500 LBS"
    - `675`  ->  "675 LB"  /  "675"
    - `400`  ->  "400 LB"  /  "400 LBS"
    - `2550`  ->  "2,550 LB"  /  "2,550 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Carrying Capacity(WC)`
- categories: **1**  ·  peak reach: **3309**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17,000 LB"
    - `2500`  ->  "2500 lbs."  /  "2,500 LB"
    - `6000`  ->  "6000 lbs."  /  "6,000 LB"
    - `7000`  ->  "7000 lbs."  /  "7,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `WC Tongue Weight`  vs  `Weight Distribution Tongue Weight (WDTW)`
- categories: **1**  ·  peak reach: **3300**  ·  mean jaccard: 0.44  ·  max containment: 0.67
- shared values (sig -> forms):
    - `500`  ->  "500"  /  "500 LBS"
    - `675`  ->  "675"  /  "675"
    - `400`  ->  "400"  /  "400 LBS"
    - `2550`  ->  "2550"  /  "2,550 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Carrying Capacity(WC)`
- categories: **1**  ·  peak reach: **3297**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LB"
    - `6000`  ->  "6000"  /  "6,000 LB"
    - `7000`  ->  "7000"  /  "7,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Carrying Capacity`
- categories: **1**  ·  peak reach: **3289**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17000"
    - `2500`  ->  "2500 lbs."  /  "2500"
    - `6000`  ->  "6000 lbs."  /  "6000"
    - `7000`  ->  "7000 lbs."  /  "7000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Carrying Capacity`
- categories: **1**  ·  peak reach: **3277**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `2500`  ->  "2500"  /  "2500"
    - `6000`  ->  "6000"  /  "6000"
    - `7000`  ->  "7000"  /  "7000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **3257**  ·  mean jaccard: 0.45  ·  max containment: 0.78
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17,000 LB"
    - `12000`  ->  "12000 lbs."  /  "12,000 LBS"
    - `7000`  ->  "7000 lbs."  /  "7,000 LBS"
    - `18000`  ->  "18000 lbs."  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **3245**  ·  mean jaccard: 0.45  ·  max containment: 0.78
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
    - `18000`  ->  "18000"  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity(WC)`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **3216**  ·  mean jaccard: 0.52  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `12000`  ->  "12,000 LB"  /  "12,000 LBS"
    - `7000`  ->  "7,000 LB"  /  "7,000 LBS"
    - `18000`  ->  "18,000 LB"  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **3196**  ·  mean jaccard: 0.52  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
    - `18000`  ->  "18000"  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Receiver Size`  vs  `Receiver Tube Size`
- categories: **1**  ·  peak reach: **3085**  ·  mean jaccard: 0.62  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2 / 2`  ->  "2 Inches X 2 Inches"  /  "2.000 in. x 2.000 in."
    - `1 / 1 / 4`  ->  "1-1/4 inch"  /  "1-1/4 IN"
    - `2`  ->  "2 inch"  /  "2.000 in."
    - `3`  ->  "3"  /  "3 IN"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Gross Trailer Weight`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **3078**  ·  mean jaccard: 0.46  ·  max containment: 0.67
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LB"
    - `18000`  ->  "18000"  /  "18,000 LB"
    - `8000`  ->  "8000"  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Package Quantity`  vs  `This Product Includes`
- categories: **1**  ·  peak reach: **3055**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 Filters"
    - `20`  ->  "20"  /  "Bulk - 20 Filters"
    - `3`  ->  "3"  /  "3 Filters"
- in: Truck Accessories > Air Intakes

### `WD Tongue Weight`  vs  `Weight Distribution Tongue Weight(WDTW)`
- categories: **1**  ·  peak reach: **2652**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `450`  ->  "450"  /  "450 LB"
    - `500`  ->  "500"  /  "500 LB"
    - `650`  ->  "650"  /  "650 LB"
    - `1600`  ->  "1600"  /  "1,600 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Carrying Capacity (WC)`
- categories: **1**  ·  peak reach: **2546**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17,000 LB"
    - `2500`  ->  "2500 lbs."  /  "2,500 LBS"
    - `6000`  ->  "6000 lbs."  /  "6,000 LBS"
    - `7000`  ->  "7000 lbs."  /  "7,000 LBS"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Carrying Capacity (WC)`
- categories: **1**  ·  peak reach: **2534**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LBS"
    - `6000`  ->  "6000"  /  "6,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight (TW)`  vs  `Weight Distribution Tongue Weight (WDTW)`
- categories: **1**  ·  peak reach: **2495**  ·  mean jaccard: 0.52  ·  max containment: 0.81
- shared values (sig -> forms):
    - `500`  ->  "500 LBS"  /  "500 LBS"
    - `675`  ->  "675 LBS"  /  "675"
    - `400`  ->  "400 LBS"  /  "400 LBS"
    - `1600`  ->  "1,600 LB"  /  "1,600 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity (WC)`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **2453**  ·  mean jaccard: 0.52  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `12000`  ->  "12,000 LBS"  /  "12,000 LBS"
    - `7000`  ->  "7,000 LBS"  /  "7,000 LBS"
    - `18000`  ->  "18,000 LB"  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Tongue Weight`  vs  `Tongue Weight(TW)`
- categories: **1**  ·  peak reach: **2244**  ·  mean jaccard: 0.58  ·  max containment: 0.84
- shared values (sig -> forms):
    - `400`  ->  "400"  /  "400 LB"
    - `900`  ->  "900"  /  "900 LB"
    - `600`  ->  "600"  /  "600 LB"
    - `250`  ->  "250"  /  "250 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Tongue Weight`  vs  `WC Tongue Weight`
- categories: **1**  ·  peak reach: **2205**  ·  mean jaccard: 0.58  ·  max containment: 0.84
- shared values (sig -> forms):
    - `400`  ->  "400"  /  "400"
    - `900`  ->  "900"  /  "900"
    - `600`  ->  "600"  /  "600"
    - `250`  ->  "250"  /  "250"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Maximum Gross Trailer Weight`
- categories: **1**  ·  peak reach: **2168**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17000"
    - `2500`  ->  "2500 lbs."  /  "2500"
    - `6000`  ->  "6000 lbs."  /  "6000"
    - `7000`  ->  "7000 lbs."  /  "7000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Maximum Gross Trailer Weight`
- categories: **1**  ·  peak reach: **2156**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `2500`  ->  "2500"  /  "2500"
    - `6000`  ->  "6000"  /  "6000"
    - `7000`  ->  "7000"  /  "7000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Gross Trailer Weight`  vs  `Weight Carrying Capacity(WC)`
- categories: **1**  ·  peak reach: **2127**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LB"
    - `6000`  ->  "6000"  /  "6,000 LB"
    - `7000`  ->  "7000"  /  "7,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Gross Trailer Weight`  vs  `Weight Carrying Capacity`
- categories: **1**  ·  peak reach: **2107**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `2500`  ->  "2500"  /  "2500"
    - `6000`  ->  "6000"  /  "6000"
    - `7000`  ->  "7000"  /  "7000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Gross Trailer Weight`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **2075**  ·  mean jaccard: 0.52  ·  max containment: 0.72
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
    - `18000`  ->  "18000"  /  "18,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Tongue Weight`  vs  `Weight Distribution Tongue Weight (WDTW)`
- categories: **1**  ·  peak reach: **2071**  ·  mean jaccard: 0.47  ·  max containment: 0.81
- shared values (sig -> forms):
    - `500`  ->  "500 LBS"  /  "500 LBS"
    - `675`  ->  "675"  /  "675"
    - `400`  ->  "400"  /  "400 LBS"
    - `2550`  ->  "2550"  /  "2,550 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **1740**  ·  mean jaccard: 0.42  ·  max containment: 0.76
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17000"
    - `12000`  ->  "12000 lbs."  /  "12000"
    - `18000`  ->  "18000 lbs."  /  "18000"
    - `8000`  ->  "8000 lbs."  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **1728**  ·  mean jaccard: 0.42  ·  max containment: 0.76
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `12000`  ->  "12000"  /  "12000"
    - `18000`  ->  "18000"  /  "18000"
    - `8000`  ->  "8000"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity(WC)`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **1699**  ·  mean jaccard: 0.48  ·  max containment: 0.71
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17000"
    - `12000`  ->  "12,000 LB"  /  "12000"
    - `18000`  ->  "18,000 LB"  /  "18000"
    - `8000`  ->  "8,000 LB"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **1679**  ·  mean jaccard: 0.48  ·  max containment: 0.71
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `12000`  ->  "12000"  /  "12000"
    - `18000`  ->  "18000"  /  "18000"
    - `8000`  ->  "8000"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `WD Tongue Weight`  vs  `Weight Distribution Tongue Weight (WDTW)`
- categories: **1**  ·  peak reach: **1647**  ·  mean jaccard: 0.81  ·  max containment: 1.00
- shared values (sig -> forms):
    - `450`  ->  "450"  /  "450 LB"
    - `500`  ->  "500"  /  "500 LBS"
    - `650`  ->  "650"  /  "650 LB"
    - `1600`  ->  "1600"  /  "1,600 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Avg Install time`  vs  `Install Time`
- categories: **1**  ·  peak reach: **1408**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1 / 3`  ->  "1-3 Hours"  /  "1-3 hours"
    - `7 / 8`  ->  "7-8 Hours"  /  "7-8 hours"
    - `2 / 3`  ->  "2-3 Hours"  /  "2-3 hours"
    - `4`  ->  "4 Hours"  /  "4+ Hours"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Maximum Tongue Weight`  vs  `Tongue Weight (TW)`
- categories: **1**  ·  peak reach: **1400**  ·  mean jaccard: 0.65  ·  max containment: 0.83
- shared values (sig -> forms):
    - `400`  ->  "400"  /  "400 LBS"
    - `900`  ->  "900"  /  "900 LBS"
    - `600`  ->  "600"  /  "600 LBS"
    - `2500`  ->  "2500"  /  "2,500 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Maximum Gross Trailer Weight`  vs  `Weight Carrying Capacity (WC)`
- categories: **1**  ·  peak reach: **1364**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LBS"
    - `6000`  ->  "6000"  /  "6,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Diameter`  vs  `SideStep Size`
- categories: **1**  ·  peak reach: **1240**  ·  mean jaccard: 0.50  ·  max containment: 0.71
- shared values (sig -> forms):
    - `3`  ->  "3"  /  "3in"
    - `4`  ->  "4"  /  "4in"
    - `2.5`  ->  "2.5"  /  "2.5"
    - `5`  ->  "5"  /  "5in"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Front Lift Height`  vs  `Lift/Drop Height`
- categories: **1**  ·  peak reach: **1013**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7`  ->  "7 Inches"  /  "7 in."
    - `8.5`  ->  "8.5 Inches"  /  "8.5 in."
    - `2`  ->  "2 Inches"  /  "2 in."
    - `8`  ->  "8 Inches"  /  "8 in."
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Lift/Drop Height`  vs  `Rear Lift Height`
- categories: **1**  ·  peak reach: **1012**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7`  ->  "7 in."  /  "7 Inches"
    - `8.5`  ->  "8.5 in."  /  "8.5 Inches"
    - `2`  ->  "2 in."  /  "2 Inches"
    - `8`  ->  "8 in."  /  "8 Inches"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Inside Diameter`  vs  `Item Height`
- categories: **1**  ·  peak reach: **958**  ·  mean jaccard: 0.41  ·  max containment: 0.63
- shared values (sig -> forms):
    - `3.188 / 81`  ->  "3.188 in (81 mm)"  /  "3.188 in. (81mm)"
    - `2.5 / 64`  ->  "2.5 in (64 mm)"  /  "2.500 in. (64mm)"
    - `4 / 102`  ->  "4.000 in. (102mm)"  /  "4.000 in. (102mm)"
    - `6.375 / 162`  ->  "6.375 in. (162mm)"  /  "6.375 in. (162mm)"
- in: Truck Accessories > Air Intakes

### `Weight Carrying Capacity (WC)`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **936**  ·  mean jaccard: 0.48  ·  max containment: 0.71
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17000"
    - `12000`  ->  "12,000 LBS"  /  "12000"
    - `18000`  ->  "18,000 LB"  /  "18000"
    - `8000`  ->  "8,000 LBS"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Step Pad Surface Width`  vs  `Surface Width`
- categories: **1**  ·  peak reach: **872**  ·  mean jaccard: 0.45  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3`  ->  "3""  /  "3" Main Bar"
    - `2 / 1 / 2`  ->  "2 1/2""  /  "2 1/2""
    - `4`  ->  "4""  /  "4""
    - `5`  ->  "5""  /  "5""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Product Line`  vs  `Style`
- categories: **1**  ·  peak reach: **699**  ·  mean jaccard: 0.44  ·  max containment: 0.85
- shared values (sig -> forms):
    - `4 / 15`  ->  "4" + 15 Degree wheel to wheel side bars"  /  "4" + 15 Side Steps"
    - `2`  ->  "Dominator Xtreme D2 SideSteps - Complete Kit: SideStep + Brackets"  /  "Dominator Xtreme D2"
    - `3`  ->  "V-Series V3 Side Step"  /  "V-Series V3"
    - `6000`  ->  "6000 Series SideSteps™ - One Piece"  /  "6000 Series"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Front Flare Height`  vs  `Rear Flare Height`
- categories: **1**  ·  peak reach: **676**  ·  mean jaccard: 0.50  ·  max containment: 0.68
- shared values (sig -> forms):
    - `7.5`  ->  "7.50"  /  "7.50"
    - `2.63`  ->  "2.63"  /  "2.63"
    - `4`  ->  "4.00"  /  "4.00"
    - `2.5`  ->  "2.50"  /  "2.50"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `SideStep Size`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **663**  ·  mean jaccard: 0.71  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3`  ->  "3in"  /  "3""
    - `2 / 1 / 2`  ->  "2 1/2in"  /  "2 1/2""
    - `4`  ->  "4in"  /  "4""
    - `5`  ->  "5in"  /  "5""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Rear Flare Height`  vs  `Rear Flare Tire Coverage`
- categories: **1**  ·  peak reach: **662**  ·  mean jaccard: 0.51  ·  max containment: 0.73
- shared values (sig -> forms):
    - `7.5`  ->  "7.50"  /  "7.50"
    - `2.63`  ->  "2.63"  /  "2.63"
    - `1.6`  ->  "1.60"  /  "1.60"
    - `4`  ->  "4.00"  /  "4.00"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Front Flare Width`  vs  `Rear Flare Width`
- categories: **1**  ·  peak reach: **651**  ·  mean jaccard: 0.54  ·  max containment: 0.78
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1.5`  ->  "1.5"  /  "1.5"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Tail Light Circuits`  vs  `Turn and Brake Circuits`
- categories: **1**  ·  peak reach: **642**  ·  mean jaccard: 0.50  ·  max containment: 0.71
- shared values (sig -> forms):
    - `7.5`  ->  "7.5 Amps"  /  "7.5 Amps"
    - `3`  ->  "3.0 Amps"  /  "3.0 Amps Per Circuit"
    - `10`  ->  "10.0 Amps"  /  "10.0 Amps"
    - `5`  ->  "5.0 Amps"  /  "5.0 Amps"
- in: Truck Equipment > Towing and Accessories > Hitch Wiring

### `Item Weight`  vs  `Weight`
- categories: **1**  ·  peak reach: **605**  ·  mean jaccard: 0.89  ·  max containment: 0.98
- shared values (sig -> forms):
    - `4.4 / 2`  ->  "4.400 lbs. (2 kg)"  /  "4.4 lb (2 kg)"
    - `15.5 / 7.1`  ->  "15.500 lbs. (7.1 kg)"  /  "15.5 lb (7.1 kg)"
    - `4.7 / 2.1`  ->  "4.700 lbs. (2.1 kg)"  /  "4.7 lb (2.1 kg)"
    - `11.4 / 5.2`  ->  "11.400 lbs. (5.2 kg)"  /  "11.4 lb (5.2 kg)"
- in: Truck Accessories > Air Intakes

### `Maximum Gross Trailer Weight`  vs  `Weight Distribution`
- categories: **1**  ·  peak reach: **558**  ·  mean jaccard: 0.48  ·  max containment: 0.71
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17000"
    - `12000`  ->  "12000"  /  "12000"
    - `18000`  ->  "18000"  /  "18000"
    - `8000`  ->  "8000"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Diameter`  vs  `Rim Diameter`
- categories: **1**  ·  peak reach: **440**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `15`  ->  "15"  /  "15"
    - `18`  ->  "18"  /  "18"
    - `20`  ->  "20"  /  "20"
    - `17`  ->  "17"  /  "17"
- in: Truck Accessories > Wheels and Tires

### `Body Diameter`  vs  `Cylinder Outside Diameter`
- categories: **1**  ·  peak reach: **412**  ·  mean jaccard: 0.55  ·  max containment: 0.92
- shared values (sig -> forms):
    - `1.86`  ->  "1.86"  /  "1.86"
    - `2.181`  ->  "2.181"  /  "2.181"
    - `2.25`  ->  "2.25"  /  "2.25"
    - `60.5`  ->  "60.5"  /  "60.5"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Air Filter Oulet Length`  vs  `Air Filter Oulet Width`
- categories: **1**  ·  peak reach: **404**  ·  mean jaccard: 0.54  ·  max containment: 0.79
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2.75 / 70`  ->  "2.750 in. (70mm)"  /  "2.750 in. (70mm)"
    - `0.625 / 16`  ->  "0.625 in. (16mm)"  /  "0.625 in. (16mm)"
- in: Truck Accessories > Air Intakes

### `Rim Width`  vs  `Width`
- categories: **1**  ·  peak reach: **402**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `10`  ->  "10"  /  "10"
    - `8`  ->  "8"  /  "8"
    - `8.5`  ->  "8.5"  /  "8.5"
    - `9`  ->  "9"  /  "9"
- in: Truck Accessories > Wheels and Tires

### `Front Flare Height (inches)`  vs  `Rear Flare Height`
- categories: **1**  ·  peak reach: **369**  ·  mean jaccard: 0.41  ·  max containment: 0.74
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.50"
    - `4`  ->  "4"  /  "4.00"
    - `2.5`  ->  "2.5"  /  "2.50"
    - `5.75`  ->  "5.75"  /  "5.75"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Rear Flare Height (inches)`  vs  `Rear Flare Tire Coverage`
- categories: **1**  ·  peak reach: **366**  ·  mean jaccard: 0.50  ·  max containment: 0.92
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.50"
    - `1.6`  ->  "1.6"  /  "1.60"
    - `4`  ->  "4"  /  "4.00"
    - `2.5`  ->  "2.5"  /  "2.50"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Diameter`  vs  `Wheel Width`
- categories: **1**  ·  peak reach: **362**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `15`  ->  "15"  /  "15"
    - `18`  ->  "18"  /  "18"
    - `20`  ->  "20"  /  "20"
    - `17`  ->  "17"  /  "17"
- in: Truck Accessories > Wheels and Tires

### `Height`  vs  `Item Height`
- categories: **1**  ·  peak reach: **360**  ·  mean jaccard: 0.58  ·  max containment: 0.97
- shared values (sig -> forms):
    - `1 / 25`  ->  "1 in (25 mm)"  /  "1.000 in. (25mm)"
    - `5.688 / 144`  ->  "5.688 in (144 mm)"  /  "5.688 in. (144mm)"
    - `3.188 / 81`  ->  "3.188 in (81 mm)"  /  "3.188 in. (81mm)"
    - `2.5 / 64`  ->  "2.5 in (64 mm)"  /  "2.500 in. (64mm)"
- in: Truck Accessories > Air Intakes

### `Wheel Diameter`  vs  `Width`
- categories: **1**  ·  peak reach: **353**  ·  mean jaccard: 0.50  ·  max containment: 0.80
- shared values (sig -> forms):
    - `8.5`  ->  "8.5"  /  "8.5"
    - `8`  ->  "8"  /  "8"
    - `10`  ->  "10"  /  "10"
    - `9`  ->  "9"  /  "9"
- in: Truck Accessories > Wheels and Tires

### `Lift/Drop Height (in.)`  vs  `Rear Lift Height`
- categories: **1**  ·  peak reach: **340**  ·  mean jaccard: 0.48  ·  max containment: 0.82
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "7 Inches"
    - `2`  ->  "2"  /  "2 Inches"
    - `8`  ->  "8"  /  "8 Inches"
    - `3`  ->  "3"  /  "3 Inches"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Air Filter Outlet Width`  vs  `Intake Pipe Inlet Width`
- categories: **1**  ·  peak reach: **327**  ·  mean jaccard: 0.60  ·  max containment: 0.91
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2 / 51`  ->  "2 in (51 mm)"  /  "2 in (51 mm)"
    - `2.75 / 70`  ->  "2.750 in. (70mm)"  /  "2.750 in. (70mm)"
- in: Truck Accessories > Air Intakes

### `Height (in.)`  vs  `Item Height`
- categories: **1**  ·  peak reach: **317**  ·  mean jaccard: 0.73  ·  max containment: 0.95
- shared values (sig -> forms):
    - `1 / 25`  ->  "1.00 in. (25mm)"  /  "1.000 in. (25mm)"
    - `5.688 / 144`  ->  "5.688 in. (144 mm)"  /  "5.688 in. (144mm)"
    - `3.188 / 81`  ->  "3.188 in. (81 mm)"  /  "3.188 in. (81mm)"
    - `2.5 / 64`  ->  "2.50 in. (64mm)"  /  "2.500 in. (64mm)"
- in: Truck Accessories > Air Intakes

### `Lower Mount Type`  vs  `Upper Mount Type`
- categories: **1**  ·  peak reach: **301**  ·  mean jaccard: 0.51  ·  max containment: 0.69
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.5 / 8`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
    - `5 / 8 / 16 / 1.1 / 2`  ->  "Loop Bushing and Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"  /  "Loop Bushing and Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"
    - `12 / 1.1 / 4`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `LED Quantity`  vs  `LEDs`
- categories: **1**  ·  peak reach: **293**  ·  mean jaccard: 0.49  ·  max containment: 0.92
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `20`  ->  "20"  /  "20"
    - `8`  ->  "8"  /  "8"
    - `30`  ->  "30"  /  "30"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Offset`  vs  `Positive Offset`
- categories: **1**  ·  peak reach: **273**  ·  mean jaccard: 0.71  ·  max containment: 1.00
- shared values (sig -> forms):
    - `13`  ->  "13"  /  "13"
    - `25`  ->  "Negative 25mm"  /  "25"
    - `19`  ->  "Negative 19mm"  /  "19"
    - `12`  ->  "Negative 12mm"  /  "12"
- in: Truck Accessories > Wheels and Tires

### `LED Number`  vs  `LED Quantity`
- categories: **1**  ·  peak reach: **263**  ·  mean jaccard: 0.71  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50"
    - `60`  ->  "60"  /  "60"
    - `2`  ->  "2"  /  "2"
    - `8`  ->  "8"  /  "8"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Lower Mounting Description`  vs  `Upper Mount Type`
- categories: **1**  ·  peak reach: **259**  ·  mean jaccard: 0.49  ·  max containment: 0.69
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.5 / 8`  ->  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
    - `5 / 8 / 16 / 1.1 / 2`  ->  "Loop Bushing & Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"  /  "Loop Bushing and Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"
    - `12 / 1.1 / 4`  ->  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Product Line`  vs  `Sub-category (Line)`
- categories: **1**  ·  peak reach: **246**  ·  mean jaccard: 0.44  ·  max containment: 0.85
- shared values (sig -> forms):
    - `2`  ->  "Dominator Xtreme D2 SideSteps - Complete Kit: SideStep + Brackets"  /  "Dominator D2 SideSteps - Cab Length"
    - `3`  ->  "V-Series V3 Side Step"  /  "V-Series V3 - Complete kit: Sidestep + Brackets"
    - `6000`  ->  "6000 Series SideSteps™ - One Piece"  /  "6000 Series SideSteps - One Piece"
    - `6000 / 1`  ->  "6000 Series SideSteps™ - 1 Piece Dually Kickouts"  /  "6000 Series SideSteps - 1 Piece Dually Kickouts"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Air Filter Outlet Length`  vs  `Intake Pipe Inlet Width`
- categories: **1**  ·  peak reach: **232**  ·  mean jaccard: 0.55  ·  max containment: 0.89
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2 / 51`  ->  "2.000 in. (51mm)"  /  "2 in (51 mm)"
    - `2.75 / 70`  ->  "2.750 in. (70mm)"  /  "2.750 in. (70mm)"
- in: Truck Accessories > Air Intakes

### `Gross Towing Weight`  vs  `Towing Capacity`
- categories: **1**  ·  peak reach: **224**  ·  mean jaccard: 0.47  ·  max containment: 0.67
- shared values (sig -> forms):
    - `12000`  ->  "12,000 lbs"  /  "12000"
    - `7000`  ->  "7000"  /  "7000"
    - `40000`  ->  "40000 lbs"  /  "40000"
    - `32000`  ->  "32000 lbs"  /  "32000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Lower Mount Type`  vs  `Upper Mounting Description`
- categories: **1**  ·  peak reach: **219**  ·  mean jaccard: 0.51  ·  max containment: 0.77
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.5 / 8`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
    - `5 / 8 / 16 / 1.1 / 2`  ->  "Loop Bushing and Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"
    - `12 / 1.1 / 4`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Rim Width`  vs  `Wheel Diameter`
- categories: **1**  ·  peak reach: **211**  ·  mean jaccard: 0.57  ·  max containment: 1.00
- shared values (sig -> forms):
    - `10`  ->  "10"  /  "10"
    - `8`  ->  "8"  /  "8"
    - `8.5`  ->  "8.5"  /  "8.5"
    - `9`  ->  "9"  /  "9"
- in: Truck Accessories > Wheels and Tires

### `Maximum Lift`  vs  `Rear Lift Height`
- categories: **1**  ·  peak reach: **211**  ·  mean jaccard: 0.50  ·  max containment: 0.71
- shared values (sig -> forms):
    - `7`  ->  "7 Inch"  /  "7 Inches"
    - `2`  ->  "2 Inch"  /  "2 Inches"
    - `8`  ->  "8 Inch"  /  "8 Inches"
    - `3`  ->  "3 Inch"  /  "3 Inches"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Rim Diameter`  vs  `Wheel Width`
- categories: **1**  ·  peak reach: **200**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `18`  ->  "18"  /  "18"
    - `20`  ->  "20"  /  "20"
    - `22`  ->  "22"  /  "22"
    - `15`  ->  "15"  /  "15"
- in: Truck Accessories > Wheels and Tires

### `Lower Mount Code`  vs  `Upper Mount Code`
- categories: **1**  ·  peak reach: **193**  ·  mean jaccard: 0.57  ·  max containment: 0.78
- shared values (sig -> forms):
    - `117`  ->  "LS117"  /  "LS117"
    - `4`  ->  "XP4"  /  "XP4"
    - `23`  ->  "LS23"  /  "LS23"
    - `28`  ->  "LS28"  /  "LS28"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Full Pallet Qty`  vs  `Full Pallet Quantity`
- categories: **1**  ·  peak reach: **180**  ·  mean jaccard: 0.90  ·  max containment: 1.00
- shared values (sig -> forms):
    - `72`  ->  "72"  /  "72"
    - `18`  ->  "18"  /  "18"
    - `30`  ->  "30"  /  "30"
    - `36`  ->  "36"  /  "36"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Lower Mount Type`  vs  `Lower Mounting Description`
- categories: **1**  ·  peak reach: **180**  ·  mean jaccard: 0.78  ·  max containment: 0.94
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.7 / 16`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.7/16" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.7/16" Sleeve OAL"
    - `5 / 16 / 2.3 / 16`  ->  "Cross Pin Mount - Open Ended, 5/16" Hole ID (Both Ends) X 2.3/16" Pin Length (Hole Center to Center)"  /  "Cross Pin Mount - Open Ended; 5/16 Hole ID (Both Ends) x 2.3/16 Pin Length (Hole Center to Center)"
    - `12 / 1.5 / 8`  ->  "Loop Bushing and Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Air Filter Large End Diameter`  vs  `Base Outside Diameter`
- categories: **1**  ·  peak reach: **177**  ·  mean jaccard: 0.62  ·  max containment: 0.79
- shared values (sig -> forms):
    - `6.625 / 168`  ->  "6.625 in. (168mm)"  /  "6.625 in. (168mm)"
    - `3.5 / 89`  ->  "3.5 in (89 mm)"  /  "3.5 in (89 mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `5.188 / 132`  ->  "5.188 in (132 mm)"  /  "5.188 in (132 mm)"
- in: Truck Accessories > Air Intakes

### `Hub Bore Diameter`  vs  `Inside Diameter`
- categories: **1**  ·  peak reach: **164**  ·  mean jaccard: 0.63  ·  max containment: 0.92
- shared values (sig -> forms):
    - `106.1`  ->  "106.1"  /  "106.1"
    - `77.9`  ->  "77.9"  /  "77.9"
    - `125`  ->  "125"  /  "125"
    - `108`  ->  "108"  /  "108"
- in: Truck Accessories > Wheels and Tires

### `Receiver Size (in)`  vs  `Shank Size`
- categories: **1**  ·  peak reach: **162**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2""
    - `2.5`  ->  "2.5"  /  "2.5""
    - `3`  ->  "3"  /  "3""
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Capacity`  vs  `Work Load Limit`
- categories: **1**  ·  peak reach: **141**  ·  mean jaccard: 0.85  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1850`  ->  "1850 lb"  /  "1850 lb"
    - `1450`  ->  "1450 lb"  /  "1450 lb"
    - `600`  ->  "600"  /  "600 lb"
    - `1500`  ->  "1500 lbs"  /  "1500 lb"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `Receiver Size (in)`  vs  `Shank Size (in)`
- categories: **1**  ·  peak reach: **136**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `2.5`  ->  "2.5"  /  "2.5"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Amp Draw`  vs  `Amperage Draw`
- categories: **1**  ·  peak reach: **128**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3.43`  ->  "3.43"  /  "3.43"
    - `0.8`  ->  "0.8"  /  "0.8"
    - `7.5`  ->  "7.5"  /  "7.5"
    - `6.36`  ->  "6.36"  /  "6.36"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Ball Mount Drop Load Capacity`  vs  `Gross Towing Weight`
- categories: **1**  ·  peak reach: **124**  ·  mean jaccard: 0.46  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7000`  ->  "7000"  /  "7000"
    - `8000`  ->  "8000"  /  "8000"
    - `32000`  ->  "32000"  /  "32000 lbs"
    - `10000`  ->  "10000"  /  "10000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Motor Voltage`  vs  `Volts`
- categories: **1**  ·  peak reach: **116**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `12`  ->  "12V"  /  "12"
    - `24`  ->  "24V"  /  "24"
- in: Truck Equipment > Winches and Accessories

### `Motor Voltage`  vs  `Voltage`
- categories: **1**  ·  peak reach: **112**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `12`  ->  "12V"  /  "12V"
    - `24`  ->  "24V"  /  "24 Volt"
- in: Truck Equipment > Winches and Accessories

### `Face Size`  vs  `LED Number`
- categories: **1**  ·  peak reach: **111**  ·  mean jaccard: 0.43  ·  max containment: 0.69
- shared values (sig -> forms):
    - `50`  ->  "50 in."  /  "50"
    - `2`  ->  "2 in."  /  "2"
    - `30`  ->  "30 in."  /  "30"
    - `12`  ->  "12 in."  /  "12"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `LED Number`  vs  `Length (in.)`
- categories: **1**  ·  peak reach: **110**  ·  mean jaccard: 0.53  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50"
    - `2`  ->  "2"  /  "2"
    - `30`  ->  "30"  /  "30"
    - `12`  ->  "12"  /  "12"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Front Lift Height`  vs  `Rear Lift Height`
- categories: **1**  ·  peak reach: **107**  ·  mean jaccard: 0.79  ·  max containment: 0.88
- shared values (sig -> forms):
    - `7`  ->  "7 Inches"  /  "7 Inches"
    - `8.5`  ->  "8.5 Inches"  /  "8.5 Inches"
    - `2`  ->  "2 Inches"  /  "2 Inches"
    - `8`  ->  "8 Inches"  /  "8 Inches"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Voltage`  vs  `Volts`
- categories: **1**  ·  peak reach: **104**  ·  mean jaccard: 0.60  ·  max containment: 0.75
- shared values (sig -> forms):
    - `12`  ->  "12V"  /  "12"
    - `120`  ->  "120 Volt"  /  "120"
    - `24`  ->  "24 Volt"  /  "24"
- in: Truck Equipment > Winches and Accessories

### `Front Shocks`  vs  `Rear Shocks`
- categories: **1**  ·  peak reach: **83**  ·  mean jaccard: 0.88  ·  max containment: 1.00
- shared values (sig -> forms):
    - `5125`  ->  "Bilstein 5125"  /  "Bilstein 5125"
    - `1.1`  ->  "Falcon 1.1 Monotube"  /  "Falcon 1.1 Monotube"
    - `9550`  ->  "TeraFlex 9550"  /  "TeraFlex 9550"
    - `2.1`  ->  "Falcon 2.1 Monotube"  /  "Falcon Tow Haul 2.1"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Wattage`  vs  `Watts`
- categories: **1**  ·  peak reach: **82**  ·  mean jaccard: 0.40  ·  max containment: 0.66
- shared values (sig -> forms):
    - `45`  ->  "45-Watts"  /  "45"
    - `185`  ->  "185"  /  "185"
    - `53`  ->  "53"  /  "53"
    - `117`  ->  "117"  /  "117"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Front Flare Height (inches)`  vs  `Rear Flare Height (inches)`
- categories: **1**  ·  peak reach: **73**  ·  mean jaccard: 0.54  ·  max containment: 0.71
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.5"
    - `4`  ->  "4"  /  "4"
    - `2.5`  ->  "2.5"  /  "2.5"
    - `2.625`  ->  "2.625"  /  "2.625"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Drop Measurement`  vs  `Drop/Raise Range`
- categories: **1**  ·  peak reach: **68**  ·  mean jaccard: 0.64  ·  max containment: 0.90
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.5""
    - `22.5`  ->  "22.5"  /  "22.5""
    - `18`  ->  "18"  /  "18""
    - `17.5`  ->  "17.5"  /  "17.5""
- in: Truck Equipment > Towing and Accessories > Hitches

### `Inlet Diameter`  vs  `Neck Flange`
- categories: **1**  ·  peak reach: **62**  ·  mean jaccard: 0.67  ·  max containment: 0.86
- shared values (sig -> forms):
    - `7.313 / 186`  ->  "7.313 in. (186mm)"  /  "7.313 in. (186mm)"
    - `3.063 / 78`  ->  "3.063 in. (78mm)"  /  "3.063 in. (78mm)"
    - `2.313 / 59`  ->  "2.313 in (59 mm)"  /  "2.313 in (59 mm)"
    - `5.125 / 130`  ->  "5.125 in (130 mm)"  /  "5.125 in (130 mm)"
- in: Truck Accessories > Air Intakes

### `Length (in.)`  vs  `Overall Length (in.)`
- categories: **1**  ·  peak reach: **60**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50.000 in."
    - `2`  ->  "2"  /  "2.000 in."
    - `30`  ->  "30"  /  "30.000 in."
    - `12`  ->  "12"  /  "12.000 in."
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Lift/Drop Height (in.)`  vs  `Lift_Height`
- categories: **1**  ·  peak reach: **54**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `2.5`  ->  "2.5"  /  "2.5"
    - `1.5`  ->  "1.5"  /  "1.5"
    - `1.75`  ->  "1.75"  /  "1.75"
- in: Truck Accessories > Suspension > Leveling Kits

### `Drop (in)`  vs  `Drop/Raise Range`
- categories: **1**  ·  peak reach: **54**  ·  mean jaccard: 0.62  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17.5`  ->  "17.5"  /  "17.5""
    - `22.5`  ->  "22.5"  /  "22.5""
    - `18`  ->  "18"  /  "18""
    - `7.5`  ->  "7.5"  /  "7.5""
- in: Truck Equipment > Towing and Accessories > Hitches

### `Diameter`  vs  `Height`
- categories: **1**  ·  peak reach: **53**  ·  mean jaccard: 0.56  ·  max containment: 0.83
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "7"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `3.5`  ->  "3.5"  /  "3.5"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Ball Mount Drop`  vs  `Drop (in)`
- categories: **1**  ·  peak reach: **51**  ·  mean jaccard: 0.41  ·  max containment: 0.60
- shared values (sig -> forms):
    - `18`  ->  "18"  /  "18"
    - `12`  ->  "12"  /  "12"
    - `20`  ->  "20"  /  "20"
    - `9`  ->  "9"  /  "9"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Drop (in)`  vs  `Drop Measurement`
- categories: **1**  ·  peak reach: **50**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17.5`  ->  "17.5"  /  "17.5"
    - `22.5`  ->  "22.5"  /  "22.5"
    - `18`  ->  "18"  /  "18"
    - `7.5`  ->  "7.5"  /  "7.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Drop/Raise Range`  vs  `Rise (in)`
- categories: **1**  ·  peak reach: **50**  ·  mean jaccard: 0.59  ·  max containment: 0.94
- shared values (sig -> forms):
    - `17.5`  ->  "17.5""  /  "17.5"
    - `22.5`  ->  "22.5""  /  "22.5"
    - `18`  ->  "18""  /  "18"
    - `7.5`  ->  "7.5""  /  "7.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Front Lift Height`  vs  `Lift Height`
- categories: **1**  ·  peak reach: **49**  ·  mean jaccard: 0.60  ·  max containment: 0.86
- shared values (sig -> forms):
    - `2`  ->  "2 Inches"  /  "2 in"
    - `3`  ->  "3 Inches"  /  "3"
    - `2.5`  ->  "2.5 Inches"  /  "2.5 in"
    - `1.5`  ->  "1.5 Inches"  /  "1.5"
- in: Truck Accessories > Suspension > Leveling Kits

### `Drop Measurement`  vs  `Rise (in)`
- categories: **1**  ·  peak reach: **46**  ·  mean jaccard: 0.76  ·  max containment: 0.94
- shared values (sig -> forms):
    - `17.5`  ->  "17.5"  /  "17.5"
    - `22.5`  ->  "22.5"  /  "22.5"
    - `18`  ->  "18"  /  "18"
    - `7.5`  ->  "7.5"  /  "7.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Carb/Air Horn Dia. (in.)`  vs  `CARB/Air Horn Diameter`
- categories: **1**  ·  peak reach: **46**  ·  mean jaccard: 0.86  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4.000 in."
    - `2.625`  ->  "2.625"  /  "2.625 in."
    - `4.25`  ->  "4.25"  /  "4.250 in."
    - `5`  ->  "5"  /  "5.000 in."
- in: Truck Accessories > Air Intakes

### `Carb/Air Horn Dia. (in.)`  vs  `CARB/Air Horn Diameter (in.)`
- categories: **1**  ·  peak reach: **46**  ·  mean jaccard: 0.86  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4.000 in."
    - `2.625`  ->  "2.625"  /  "2.625 in."
    - `4.25`  ->  "4.25"  /  "4.250 in."
    - `5`  ->  "5"  /  "5.000 in."
- in: Truck Accessories > Air Intakes

### `Rated Single Line Pull (lbs.)`  vs  `Winch Rating`
- categories: **1**  ·  peak reach: **46**  ·  mean jaccard: 0.62  ·  max containment: 0.94
- shared values (sig -> forms):
    - `12000`  ->  "12000"  /  "12000 Pound"
    - `18000`  ->  "18000"  /  "18000 Pound"
    - `5500`  ->  "5500"  /  "5500 Pound"
    - `3500`  ->  "3500"  /  "3500 Pound"
- in: Truck Equipment > Winches and Accessories

### `Rated Line Pull`  vs  `Winch Rating`
- categories: **1**  ·  peak reach: **44**  ·  mean jaccard: 0.61  ·  max containment: 0.88
- shared values (sig -> forms):
    - `12000`  ->  "12000"  /  "12000 Pound"
    - `18000`  ->  "18000"  /  "18000 Pound"
    - `5500`  ->  "5500"  /  "5500 Pound"
    - `3500`  ->  "3500"  /  "3500 Pound"
- in: Truck Equipment > Winches and Accessories

### `Tire Info`  vs  `Tire Information`
- categories: **1**  ·  peak reach: **42**  ·  mean jaccard: 0.73  ·  max containment: 0.86
- shared values (sig -> forms):
    - `38 / 13.5 / 17 / 17 / 8.5 / 8 / 170 / 0 / 38 / 13.5 / 17 / 17 / 8.5 / 8 / 170 / 1 / 38 / 13.5 / 17 / 17 / 9 / 8 / 170 / 12 / 38 / 12.5 / 17 / 17 / 9 / 8 / 170 / 12 / 37 / 12.5 / 17 / 17 / 9 / 8 / 170 / 12 / 38 / 13.5 / 17 / 17 / 9 / 8 / 170 / 0 / 38 / 13.5 / 17 / 17 / 9 / 8 / 170 / 1 / 38 / 13.5 / 18 / 18 / 8.5 / 8 / 170 / 0 / 38 / 13.5 / 18 / 18 / 8.5 / 8 / 170 / 1 / 38 / 13.5 / 18 / 18 / 9 / 8 / 170 / 12 / 38 / 12.5 / 18 / 18 / 9 / 8 / 170 / 12 / 37 / 12.5 / 18 / 18 / 9 / 8 / 170 / 12 / 38 / 13.5 / 18 / 18 / 9 / 8 / 170 / 0 / 38 / 12.5 / 18 / 18 / 9 / 8 / 170 / 0 / 37 / 12.5 / 18 / 18 / 9 / 8 / 170 / 0 / 38 / 13.5 / 18 / 18 / 9 / 8 / 170 / 1 / 38 / 12.5 / 18 / 18 / 9 / 8 / 170 / 1 / 37 / 12.5 / 18 / 18 / 9 / 8 / 170 / 1 / 37 / 13.5 / 18 / 18 / 10 / 8 / 170 / 25 / 37 / 13.5 / 18 / 18 / 10 / 8 / 170 / 19 / 37 / 13.5 / 18 / 18 / 10 / 8 / 170 / 18 / 38 / 13.5 / 20 / 20 / 9 / 8 / 170 / 12 / 38 / 12.5 / 20 / 20 / 9 / 8 / 170 / 12 / 37 / 12.5 / 20 / 20 / 9 / 8 / 170 / 12 / 38 / 13.5 / 20 / 20 / 9 / 8 / 170 / 0 / 38 / 13.5 / 20 / 20 / 9 / 8 / 170 / 1 / 37 / 13.5 / 20 / 20 / 10 / 8 / 170 / 25 / 37 / 13.5 / 20 / 20 / 10 / 8 / 170 / 19 / 37 / 12.5 / 20 / 20 / 10 / 8 / 170 / 19 / 37 / 13.5 / 20 / 20 / 10 / 8 / 170 / 18 / 37 / 12.5 / 20 / 20 / 10 / 8 / 170 / 18 / 37 / 13.5 / 20 / 20 / 12 / 8 / 170 / 44 / 37 / 12.5 / 20 / 20 / 12 / 8 / 170 / 44 / 37 / 13.5 / 22 / 22 / 10 / 8 / 170 / 25 / 37 / 13.5 / 22 / 22 / 10 / 8 / 170 / 19 / 37 / 12.5 / 22 / 22 / 10 / 8 / 170 / 19 / 37 / 13.5 / 22 / 22 / 10 / 8 / 170 / 18 / 37 / 12.5 / 22 / 22 / 10 / 8 / 170 / 18 / 37 / 13.5 / 22 / 22 / 12 / 8 / 170 / 44 / 37 / 12.5 / 22 / 22 / 12 / 8 / 170 / 44`  ->  "38x13.50R17:17x8.5:8x170:+0:-;38x13.50R17:17x8.5:8x170:+1:-;38x13.50R17:17x9:8x170:-12:-;38x12.50R17:17x9:8x170:-12:-;37x12.50R17:17x9:8x170:-12:-;38x13.50R17:17x9:8x170:+0:-;38x13.50R17:17x9:8x170:+1:-;38x13.50R18:18x8.5:8x170:+0:-;38x13.50R18:18x8.5:8x170:+1:-;38x13.50R18:18x9:8x170:-12:-;38x12.50R18:18x9:8x170:-12:-;37x12.50R18:18x9:8x170:-12:-;38x13.50R18:18x9:8x170:+0:-;38x12.50R18:18x9:8x170:+0:-;37x12.50R18:18x9:8x170:+0:-;38x13.50R18:18x9:8x170:+1:-;38x12.50R18:18x9:8x170:+1:-;37x12.50R18:18x9:8x170:+1:-;37x13.50R18:18x10:8x170:-25:Minor Trimming;37x13.50R18:18x10:8x170:-19:Minor Trimming;37x13.50R18:18x10:8x170:-18:Minor Trimming;38x13.50R20:20x9:8x170:-12:-;38x12.50R20:20x9:8x170:-12:-;37x12.50R20:20x9:8x170:-12:-;38x13.50R20:20x9:8x170:+0:-;38x13.50R20:20x9:8x170:+1:-;37x13.50R20:20x10:8x170:-25:Minor Trimming;37x13.50R20:20x10:8x170:-19:Minor Trimming;37x12.50R20:20x10:8x170:-19:Minor Trimming;37x13.50R20:20x10:8x170:-18:Minor Trimming;37x12.50R20:20x10:8x170:-18:Minor Trimming;37x13.50R20:20x12:8x170:-44:-;37x12.50R20:20x12:8x170:-44:Trimming Required;37x13.50R22:22x10:8x170:-25:Minor Trimming;37x13.50R22:22x10:8x170:-19:Minor Trimming;37x12.50R22:22x10:8x170:-19:-;37x13.50R22:22x10:8x170:-18:Minor Trimming;37x12.50R22:22x10:8x170:-18:-;37x13.50R22:22x12:8x170:-44:-;37x12.50R22:22x12:8x170:-44:Trimming Required"  /  "38x13.50R17:17x8.5:8x170:+0:-;38x13.50R17:17x8.5:8x170:+1:-;38x13.50R17:17x9:8x170:-12:-;38x12.50R17:17x9:8x170:-12:-;37x12.50R17:17x9:8x170:-12:-;38x13.50R17:17x9:8x170:+0:-;38x13.50R17:17x9:8x170:+1:-;38x13.50R18:18x8.5:8x170:+0:-;38x13.50R18:18x8.5:8x170:+1:-;38x13.50R18:18x9:8x170:-12:-;38x12.50R18:18x9:8x170:-12:-;37x12.50R18:18x9:8x170:-12:-;38x13.50R18:18x9:8x170:+0:-;38x12.50R18:18x9:8x170:+0:-;37x12.50R18:18x9:8x170:+0:-;38x13.50R18:18x9:8x170:+1:-;38x12.50R18:18x9:8x170:+1:-;37x12.50R18:18x9:8x170:+1:-;37x13.50R18:18x10:8x170:-25:Minor Trimming;37x13.50R18:18x10:8x170:-19:Minor Trimming;37x13.50R18:18x10:8x170:-18:Minor Trimming;38x13.50R20:20x9:8x170:-12:-;38x12.50R20:20x9:8x170:-12:-;37x12.50R20:20x9:8x170:-12:-;38x13.50R20:20x9:8x170:+0:-;38x13.50R20:20x9:8x170:+1:-;37x13.50R20:20x10:8x170:-25:Minor Trimming;37x13.50R20:20x10:8x170:-19:Minor Trimming;37x12.50R20:20x10:8x170:-19:Minor Trimming;37x13.50R20:20x10:8x170:-18:Minor Trimming;37x12.50R20:20x10:8x170:-18:Minor Trimming;37x13.50R20:20x12:8x170:-44:-;37x12.50R20:20x12:8x170:-44:Trimming Required;37x13.50R22:22x10:8x170:-25:Minor Trimming;37x13.50R22:22x10:8x170:-19:Minor Trimming;37x12.50R22:22x10:8x170:-19:-;37x13.50R22:22x10:8x170:-18:Minor Trimming;37x12.50R22:22x10:8x170:-18:-;37x13.50R22:22x12:8x170:-44:-;37x12.50R22:22x12:8x170:-44:Trimming Required"
    - `35 / 12.5 / 15 / 15 / 5 / 5.5 / 35 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 19 / 35 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 18 / 35 / 12.5 / 16 / 16 / 8 / 5 / 5.5 / 19 / 35 / 12.5 / 16 / 16 / 8 / 5 / 5.5 / 18 / 35 / 12.5 / 17 / 17 / 8.5 / 5 / 5.5 / 0 / 35 / 12.5 / 17 / 17 / 8.5 / 5 / 5.5 / 1 / 35 / 12.5 / 17 / 17 / 9 / 5 / 5.5 / 12 / 35 / 12.5 / 17 / 17 / 9 / 5 / 5.5 / 0 / 305 / 70 / 17 / 17 / 9 / 5 / 5.5 / 0 / 35 / 12.5 / 17 / 17 / 9 / 5 / 5.5 / 1 / 305 / 70 / 17 / 17 / 9 / 5 / 5.5 / 1 / 35 / 12.5 / 18 / 18 / 8.5 / 5 / 5.5 / 0 / 295 / 70 / 18 / 18 / 8.5 / 5 / 5.5 / 0 / 35 / 12.5 / 18 / 18 / 8.5 / 5 / 5.5 / 1 / 295 / 70 / 18 / 18 / 8.5 / 5 / 5.5 / 1 / 35 / 12.5 / 18 / 18 / 9 / 5 / 5.5 / 12 / 295 / 70 / 18 / 18 / 9 / 5 / 5.5 / 12 / 285 / 75 / 18 / 18 / 9 / 5 / 5.5 / 12 / 35 / 12.5 / 18 / 18 / 9 / 5 / 5.5 / 0 / 295 / 70 / 18 / 18 / 9 / 5 / 5.5 / 0 / 35 / 12.5 / 18 / 18 / 9 / 5 / 5.5 / 1 / 295 / 70 / 18 / 18 / 9 / 5 / 5.5 / 1 / 295 / 70 / 18 / 18 / 10 / 5 / 5.5 / 25 / 295 / 70 / 18 / 18 / 10 / 5 / 5.5 / 19 / 295 / 70 / 18 / 18 / 10 / 5 / 5.5 / 18 / 35 / 12.5 / 20 / 20 / 9 / 5 / 5.5 / 12 / 35 / 12.5 / 20 / 20 / 9 / 5 / 5.5 / 0 / 295 / 60 / 20 / 20 / 9 / 5 / 5.5 / 0 / 35 / 12.5 / 20 / 20 / 9 / 5 / 5.5 / 1 / 295 / 60 / 20 / 20 / 9 / 5 / 5.5 / 1 / 295 / 60 / 20 / 20 / 10 / 5 / 5.5 / 19 / 295 / 60 / 20 / 20 / 10 / 5 / 5.5 / 18 / 35 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 19 / 285 / 55 / 22 / 22 / 10 / 5 / 5.5 / 19 / 35 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 18 / 285 / 55 / 22 / 22 / 10 / 5 / 5.5 / 18 / 35 / 12.5 / 22 / 22 / 12 / 5 / 5.5 / 44`  ->  "35x12.50R15:Factory 15:5x5.5:-:-;35x12.50R15:15x8:5x5.5:-19:-;35x12.50R15:15x8:5x5.5:-18:-;35x12.50R16:16x8:5x5.5:-19:-;35x12.50R16:16x8:5x5.5:-18:-;35x12.50R17:17x8.5:5x5.5:+0:-;35x12.50R17:17x8.5:5x5.5:+1:-;35x12.50R17:17x9:5x5.5:-12:-;35x12.50R17:17x9:5x5.5:+0:-;305/70R17:17x9:5x5.5:+0:-;35x12.50R17:17x9:5x5.5:+1:-;305/70R17:17x9:5x5.5:+1:-;35x12.50R18:18x8.5:5x5.5:+0:-;295/70R18:18x8.5:5x5.5:+0:-;35x12.50R18:18x8.5:5x5.5:+1:-;295/70R18:18x8.5:5x5.5:+1:-;35x12.50R18:18x9:5x5.5:-12:-;295/70R18:18x9:5x5.5:-12:-;285/75R18:18x9:5x5.5:-12:-;35x12.50R18:18x9:5x5.5:+0:-;295/70R18:18x9:5x5.5:+0:-;35x12.50R18:18x9:5x5.5:+1:-;295/70R18:18x9:5x5.5:+1:-;295/70R18:18x10:5x5.5:-25:-;295/70R18:18x10:5x5.5:-19:-;295/70R18:18x10:5x5.5:-18:-;35x12.50R20:20x9:5x5.5:-12:-;35x12.50R20:20x9:5x5.5:+0:-;295/60R20:20x9:5x5.5:+0:-;35x12.50R20:20x9:5x5.5:+1:-;295/60R20:20x9:5x5.5:+1:-;295/60R20:20x10:5x5.5:-19:Minor Trimming;295/60R20:20x10:5x5.5:-18:Minor Trimming;35x12.50R22:22x10:5x5.5:-19:Minor Trimming;285/55R22:22x10:5x5.5:-19:-;35x12.50R22:22x10:5x5.5:-18:Minor Trimming;285/55R22:22x10:5x5.5:-18:-;35x12.50R22:22x12:5x5.5:-44:Trimming Required"  /  "35x12.50R15:Factory 15:5x5.5:-:-;35x12.50R15:15x8:5x5.5:-19:-;35x12.50R15:15x8:5x5.5:-18:-;35x12.50R16:16x8:5x5.5:-19:-;35x12.50R16:16x8:5x5.5:-18:-;35x12.50R17:17x8.5:5x5.5:+0:-;35x12.50R17:17x8.5:5x5.5:+1:-;35x12.50R17:17x9:5x5.5:-12:-;35x12.50R17:17x9:5x5.5:+0:-;305/70R17:17x9:5x5.5:+0:-;35x12.50R17:17x9:5x5.5:+1:-;305/70R17:17x9:5x5.5:+1:-;35x12.50R18:18x8.5:5x5.5:+0:-;295/70R18:18x8.5:5x5.5:+0:-;35x12.50R18:18x8.5:5x5.5:+1:-;295/70R18:18x8.5:5x5.5:+1:-;35x12.50R18:18x9:5x5.5:-12:-;295/70R18:18x9:5x5.5:-12:-;285/75R18:18x9:5x5.5:-12:-;35x12.50R18:18x9:5x5.5:+0:-;295/70R18:18x9:5x5.5:+0:-;35x12.50R18:18x9:5x5.5:+1:-;295/70R18:18x9:5x5.5:+1:-;295/70R18:18x10:5x5.5:-25:-;295/70R18:18x10:5x5.5:-19:-;295/70R18:18x10:5x5.5:-18:-;35x12.50R20:20x9:5x5.5:-12:-;35x12.50R20:20x9:5x5.5:+0:-;295/60R20:20x9:5x5.5:+0:-;35x12.50R20:20x9:5x5.5:+1:-;295/60R20:20x9:5x5.5:+1:-;295/60R20:20x10:5x5.5:-19:Minor Trimming;295/60R20:20x10:5x5.5:-18:Minor Trimming;35x12.50R22:22x10:5x5.5:-19:Minor Trimming;285/55R22:22x10:5x5.5:-19:-;35x12.50R22:22x10:5x5.5:-18:Minor Trimming;285/55R22:22x10:5x5.5:-18:-;35x12.50R22:22x12:5x5.5:-44:Trimming Required"
    - `245 / 65 / 17 / 17 / 7.5 / 5 / 108 / 35 / 245 / 65 / 17 / 17 / 8 / 5 / 108 / 38`  ->  "245/65R17:17x7.5:5x108:+35:-;245/65R17:17x8:5x108:+38:-"  /  "245/65R17:17x7.5:5x108:+35:-;245/65R17:17x8:5x108:+38:-"
    - `35 / 12.5 / 15 / 15 / 5 / 5.5 / 33 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 19 / 33 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 18 / 33 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 18 / 33 / 12.5 / 15 / 15 / 8 / 5 / 5.5 / 20 / 33 / 12.5 / 15 / 15 / 10 / 5 / 5.5 / 39 / 295 / 70 / 18 / 18 / 8.5 / 5 / 5.5 / 0 / 295 / 70 / 18 / 18 / 8.5 / 5 / 5.5 / 1 / 295 / 70 / 18 / 18 / 10 / 5 / 5.5 / 19 / 295 / 70 / 18 / 18 / 10 / 5 / 5.5 / 18 / 35 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 19 / 33 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 19 / 285 / 55 / 22 / 22 / 10 / 5 / 5.5 / 19 / 35 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 18 / 33 / 12.5 / 22 / 22 / 10 / 5 / 5.5 / 18 / 285 / 55 / 22 / 22 / 10 / 5 / 5.5 / 18 / 35 / 12.5 / 22 / 22 / 12 / 5 / 5.5 / 44`  ->  "35x12.50R15:Factory 15:5x5.5:-:-;33x12.50R15:15x8:5x5.5:-19:-;33x12.50R15:15x8:5x5.5:-18:-;33x12.50R15:15x8:5x5.5:+18:-;33x12.50R15:15x8:5x5.5:+20:-;33x12.50R15:15x10:5x5.5:-39:Trimming Required;295/70R18:18x8.5:5x5.5:+0:-;295/70R18:18x8.5:5x5.5:+1:-;295/70R18:18x10:5x5.5:-19:-;295/70R18:18x10:5x5.5:-18:-;35x12.50R22:22x10:5x5.5:-19:Minor Trimming;33x12.50R22:22x10:5x5.5:-19:Minor Trimming;285/55R22:22x10:5x5.5:-19:-;35x12.50R22:22x10:5x5.5:-18:Minor Trimming;33x12.50R22:22x10:5x5.5:-18:Minor Trimming;285/55R22:22x10:5x5.5:-18:-;35x12.50R22:22x12:5x5.5:-44:Trimming Required"  /  "35x12.50R15:Factory 15:5x5.5:-:-;33x12.50R15:15x8:5x5.5:-19:-;33x12.50R15:15x8:5x5.5:-18:-;33x12.50R15:15x8:5x5.5:+18:-;33x12.50R15:15x8:5x5.5:+20:-;33x12.50R15:15x10:5x5.5:-39:Trimming Required;295/70R18:18x8.5:5x5.5:+0:-;295/70R18:18x8.5:5x5.5:+1:-;295/70R18:18x10:5x5.5:-19:-;295/70R18:18x10:5x5.5:-18:-;35x12.50R22:22x10:5x5.5:-19:Minor Trimming;33x12.50R22:22x10:5x5.5:-19:Minor Trimming;285/55R22:22x10:5x5.5:-19:-;35x12.50R22:22x10:5x5.5:-18:Minor Trimming;33x12.50R22:22x10:5x5.5:-18:Minor Trimming;285/55R22:22x10:5x5.5:-18:-;35x12.50R22:22x12:5x5.5:-44:Trimming Required"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Diameter (IN)`  vs  `Line Diameter (IN)`
- categories: **1**  ·  peak reach: **36**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1 / 4`  ->  "1/4 Inch"  /  "1/4 Inch"
    - `3 / 16`  ->  "3/16 Inch"  /  "3/16 Inch"
    - `3 / 8`  ->  "3/8 Inch"  /  "3/8 Inch"
    - `5 / 16`  ->  "5/16 Inch"  /  "5/16 Inch"
- in: Truck Equipment > Winches and Accessories

### `Power Consumption`  vs  `Watts`
- categories: **1**  ·  peak reach: **34**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `18`  ->  "18 Watt"  /  "18"
    - `45`  ->  "45 Watt"  /  "45"
- in: Truck Accessories > Automotive Lighting > LED Headlight Conversion Kits

### `Drop (in)`  vs  `Rise Measurement`
- categories: **1**  ·  peak reach: **34**  ·  mean jaccard: 0.47  ·  max containment: 0.89
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.5"
    - `5`  ->  "5"  /  "5"
    - `20`  ->  "20"  /  "20"
    - `2.5`  ->  "2.5"  /  "2.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Drop (in)`  vs  `Rise (in)`
- categories: **1**  ·  peak reach: **32**  ·  mean jaccard: 0.94  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17.5`  ->  "17.5"  /  "17.5"
    - `22.5`  ->  "22.5"  /  "22.5"
    - `18`  ->  "18"  /  "18"
    - `7.5`  ->  "7.5"  /  "7.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Front Lift Height`  vs  `Lift_Height`
- categories: **1**  ·  peak reach: **31**  ·  mean jaccard: 0.62  ·  max containment: 0.83
- shared values (sig -> forms):
    - `2`  ->  "2 Inches"  /  "2"
    - `2.5`  ->  "2.5 Inches"  /  "2.5"
    - `1.5`  ->  "1.5 Inches"  /  "1.5"
    - `1.75`  ->  "1.75 Inches"  /  "1.75"
- in: Truck Accessories > Suspension > Leveling Kits

### `Rise (in)`  vs  `Rise Measurement`
- categories: **1**  ·  peak reach: **30**  ·  mean jaccard: 0.53  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7.5`  ->  "7.5"  /  "7.5"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
    - `2.5`  ->  "2.5"  /  "2.5"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Rated Single Line Pull (lbs.)`  vs  `Rating`
- categories: **1**  ·  peak reach: **30**  ·  mean jaccard: 0.42  ·  max containment: 0.61
- shared values (sig -> forms):
    - `12000`  ->  "12000"  /  "12000"
    - `9500`  ->  "9500"  /  "9500"
    - `18000`  ->  "18000"  /  "18000"
    - `8000`  ->  "8000"  /  "8000"
- in: Truck Equipment > Winches and Accessories

### `Cable Diameter`  vs  `Line Diameter (IN)`
- categories: **1**  ·  peak reach: **28**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3 / 8`  ->  "3/8"  /  "3/8 Inch"
    - `1 / 4`  ->  "1/4"  /  "1/4 Inch"
    - `3 / 16`  ->  "3/16"  /  "3/16 Inch"
    - `7 / 32`  ->  "7/32"  /  "7/32 Inch"
- in: Truck Equipment > Winches and Accessories

### `Rated Line Pull`  vs  `Rating`
- categories: **1**  ·  peak reach: **28**  ·  mean jaccard: 0.50  ·  max containment: 0.71
- shared values (sig -> forms):
    - `12000`  ->  "12000"  /  "12000"
    - `9500`  ->  "9500"  /  "9500"
    - `18000`  ->  "18000"  /  "18000"
    - `8000`  ->  "8000"  /  "8000"
- in: Truck Equipment > Winches and Accessories

### `Rated Line Pull`  vs  `Rated Single Line Pull (lbs.)`
- categories: **1**  ·  peak reach: **26**  ·  mean jaccard: 0.76  ·  max containment: 0.90
- shared values (sig -> forms):
    - `16500`  ->  "16500"  /  "16500"
    - `2500`  ->  "2,500"  /  "2500"
    - `9000`  ->  "9000"  /  "9000"
    - `6000`  ->  "6,000"  /  "6000"
- in: Truck Equipment > Winches and Accessories

### `Length (FT)`  vs  `Line Length`
- categories: **1**  ·  peak reach: **25**  ·  mean jaccard: 0.50  ·  max containment: 0.80
- shared values (sig -> forms):
    - `50`  ->  "50 Feet"  /  "50"
    - `60`  ->  "60 Feet"  /  "60"
    - `125`  ->  "125 Feet"  /  "125"
    - `100`  ->  "100 Foot"  /  "100"
- in: Truck Equipment > Winches and Accessories

### `Length (FT)`  vs  `Line Length (FT)`
- categories: **1**  ·  peak reach: **24**  ·  mean jaccard: 0.48  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50 Feet"  /  "50 Feet"
    - `60`  ->  "60 Feet"  /  "60 Feet"
    - `125`  ->  "125 Feet"  /  "125 Feet"
    - `30`  ->  "30 Meter"  /  "30 Feet"
- in: Truck Equipment > Winches and Accessories

### `Length (FT)`  vs  `Product Length`
- categories: **1**  ·  peak reach: **24**  ·  mean jaccard: 0.62  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50 Feet"  /  "50 ft."
    - `60`  ->  "60 Feet"  /  "60 ft."
    - `140`  ->  "140 Feet"  /  "140 ft."
    - `125`  ->  "125 Feet"  /  "125 ft"
- in: Truck Equipment > Winches and Accessories

### `Base Outside Width`  vs  `Top Outside Width`
- categories: **1**  ·  peak reach: **21**  ·  mean jaccard: 0.66  ·  max containment: 0.80
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.5 in (89 mm)"  /  "3.5 in (89 mm)"
    - `9.875 / 251`  ->  "9.875 in (251 mm)"  /  "9.875 in (251 mm)"
    - `2.75 / 70`  ->  "2.75 in (70 mm)"  /  "2.75 in (70 mm)"
    - `2.25 / 57`  ->  "2.25 in (57 mm)"  /  "2.25 in (57 mm)"
- in: Truck Accessories > Air Intakes

### `Lift_Height`  vs  `Maximum Lift`
- categories: **1**  ·  peak reach: **19**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 Inch"
    - `2.5`  ->  "2.5"  /  "2.5 Inch"
    - `1.5`  ->  "1.5"  /  "1.5"
    - `1.75`  ->  "1.75"  /  "1.75"
- in: Truck Accessories > Suspension > Leveling Kits

### `Line Length`  vs  `Product Length`
- categories: **1**  ·  peak reach: **19**  ·  mean jaccard: 0.65  ·  max containment: 0.85
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50 ft."
    - `60`  ->  "60"  /  "60 ft."
    - `125`  ->  "125"  /  "125 ft"
    - `100`  ->  "100"  /  "100 ft."
- in: Truck Equipment > Winches and Accessories

### `Line Length (FT)`  vs  `Product Length`
- categories: **1**  ·  peak reach: **18**  ·  mean jaccard: 0.53  ·  max containment: 0.80
- shared values (sig -> forms):
    - `50`  ->  "50 Feet"  /  "50 ft."
    - `60`  ->  "60 Feet"  /  "60 ft."
    - `125`  ->  "125 Feet"  /  "125 ft"
    - `100`  ->  "100 Feet"  /  "100 ft."
- in: Truck Equipment > Winches and Accessories

### `Length (in.)`  vs  `Light Bar Length`
- categories: **1**  ·  peak reach: **15**  ·  mean jaccard: 0.56  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50""
    - `30`  ->  "30"  /  "30""
    - `20`  ->  "20"  /  "20""
    - `10`  ->  "10"  /  "10""
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Breaking Strength (LB)`  vs  `Capacity`
- categories: **1**  ·  peak reach: **14**  ·  mean jaccard: 0.59  ·  max containment: 0.76
- shared values (sig -> forms):
    - `33600`  ->  "33600 Pounds"  /  "33600"
    - `12000`  ->  "12000 Pounds"  /  "12000"
    - `7000`  ->  "7000 Pounds"  /  "7000"
    - `15100`  ->  "15100 Pounds"  /  "15100"
- in: Truck Equipment > Winches and Accessories

### `Face Size`  vs  `Length (in.)`
- categories: **1**  ·  peak reach: **13**  ·  mean jaccard: 0.69  ·  max containment: 1.00
- shared values (sig -> forms):
    - `50`  ->  "50 in."  /  "50"
    - `2`  ->  "2 in."  /  "2"
    - `30`  ->  "30 in."  /  "30"
    - `12`  ->  "12 in."  /  "12"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Bed Rail Length`  vs  `Product Length`
- categories: **1**  ·  peak reach: **12**  ·  mean jaccard: 0.56  ·  max containment: 1.00
- shared values (sig -> forms):
    - `60`  ->  "60"  /  "60""
    - `47 / 1 / 2`  ->  "47 1/2"  /  "47 1/2""
    - `67 / 1 / 2`  ->  "67 1/2in"  /  "67 1/2""
    - `36`  ->  "36in"  /  "36""
- in: Truck Accessories > Cargo Management > Rack Accessories

### `Base Outside Length`  vs  `Top Outside Length`
- categories: **1**  ·  peak reach: **11**  ·  mean jaccard: 0.67  ·  max containment: 0.81
- shared values (sig -> forms):
    - `16.125 / 410`  ->  "16.125 in. (410mm)"  /  "16.125 in. (410mm)"
    - `6.625 / 168`  ->  "6.625 in. (168mm)"  /  "6.625 in. (168mm)"
    - `6 / 152`  ->  "6 in (152 mm)"  /  "6 in (152 mm)"
    - `13.875 / 352`  ->  "13.875 in (352 mm)"  /  "13.875 in (352 mm)"
- in: Truck Accessories > Air Intakes

## LABEL_VARIANT - safe auto-merge  (57)

### `Overall Length`  vs  `Overall Length (in.)`
- categories: **3**  ·  peak reach: **2082**  ·  mean jaccard: 0.82  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4.000 in."  /  "4.000 in."
    - `20`  ->  "20.000 in."  /  "20.000 in."
    - `28`  ->  "28.000 in."  /  "28.000 in."
    - `5`  ->  "5.000 in."  /  "5.000 in."
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights; Truck Equipment > Towing and Accessories > Hitches; Truck Accessories > Air Intakes

### `Parts Pack`  vs  `Parts Pack(s)`
- categories: **3**  ·  peak reach: **669**  ·  mean jaccard: 0.81  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1141 / 1726`  ->  "P01141,P01726"  /  "P01141,P01726"
    - `1577 / 1510`  ->  "P01577,P01510"  /  "P01577,P01510"
    - `1113`  ->  "P01113"  /  "P01113"
    - `1141`  ->  "P01141"  /  "P01141"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Lift/Drop Height`  vs  `Lift/Drop Height (in.)`
- categories: **2**  ·  peak reach: **1246**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2 in."  /  "2"
    - `1 / 2`  ->  "1 in. to 2 in."  /  "1-2"
    - `3`  ->  "3 in."  /  "3"
    - `2.4`  ->  "2.4 in."  /  "2.4"
- in: Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Shock Stroke`  vs  `Shock Stroke (in.)`
- categories: **2**  ·  peak reach: **386**  ·  mean jaccard: 0.74  ·  max containment: 1.00
- shared values (sig -> forms):
    - `8.01`  ->  "8.010 in."  /  "8.010"
    - `10.13`  ->  "10.130 in."  /  "10.130"
    - `5.87`  ->  "5.870 in."  /  "5.870"
    - `11.07`  ->  "11.070 in."  /  "11.070"
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Extended Length`  vs  `Extended Length (in.)`
- categories: **2**  ·  peak reach: **264**  ·  mean jaccard: 0.67  ·  max containment: 0.99
- shared values (sig -> forms):
    - `23.89`  ->  "23.89"  /  "23.890 in."
    - `24.68`  ->  "24.680 in."  /  "24.680 in."
    - `32.29`  ->  "32.29"  /  "32.290 in."
    - `18.7`  ->  "18.7"  /  "18.700 in."
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Max Year Covered`  vs  `Min Year Covered`
- categories: **2**  ·  peak reach: **170**  ·  mean jaccard: 0.47  ·  max containment: 0.94
- shared values (sig -> forms):
    - `1989`  ->  "1989"  /  "1989"
    - `2014`  ->  "2014"  /  "2014"
    - `2005`  ->  "2005"  /  "2005"
    - `2013`  ->  "2013"  /  "2013"
- in: Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Collapsed Length`  vs  `Collapsed Length (in.)`
- categories: **2**  ·  peak reach: **150**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `11.29`  ->  "11.29"  /  "11.290"
    - `13.73`  ->  "13.73"  /  "13.730"
    - `15.98`  ->  "15.98"  /  "15.980"
    - `13.98`  ->  "13.980 in."  /  "13.980"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories

### `Width`  vs  `Width (in.)`
- categories: **2**  ·  peak reach: **76**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `18 / 457`  ->  "18 in (457 mm)"  /  "18.000 in. (457mm)"
    - `17 / 432`  ->  "17 in (432 mm)"  /  "17.00 in. (432 mm)"
- in: Truck Accessories > Exterior > Hood Scoops and Vents; Truck Accessories > Air Intakes

### `Weight Distribution Tongue Weight (WDTW)`  vs  `Weight Distribution Tongue Weight(WDTW)`
- categories: **1**  ·  peak reach: **4171**  ·  mean jaccard: 0.81  ·  max containment: 1.00
- shared values (sig -> forms):
    - `450`  ->  "450 LB"  /  "450 LB"
    - `500`  ->  "500 LBS"  /  "500 LB"
    - `650`  ->  "650 LB"  /  "650 LB"
    - `1600`  ->  "1,600 LB"  /  "1,600 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Distribution (WD)`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **4167**  ·  mean jaccard: 0.89  ·  max containment: 0.94
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `12000`  ->  "12,000 LBS"  /  "12,000 LB"
    - `18000`  ->  "18,000 LB"  /  "18,000 LB"
    - `5500`  ->  "5,500 LB"  /  "5,500 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight(TW)`  vs  `WC Tongue Weight`
- categories: **1**  ·  peak reach: **3473**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `600 / 800`  ->  "600 LB - 800 LB"  /  "600  - 800"
    - `400`  ->  "400 LB"  /  "400"
    - `900`  ->  "900 LB"  /  "900"
    - `600`  ->  "600 LB"  /  "600"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Gross Trailer Weight (lbs.)`
- categories: **1**  ·  peak reach: **3338**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000 lbs."  /  "17000"
    - `6000 / 8000`  ->  "6000 lbs. - 8000 lbs."  /  "6000 - 8000"
    - `2500`  ->  "2500 lbs."  /  "2500"
    - `9000`  ->  "9000 lbs."  /  "9000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity`  vs  `Weight Carrying Capacity(WC)`
- categories: **1**  ·  peak reach: **3248**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LB"
    - `6000`  ->  "6000"  /  "6,000 LB"
    - `7000`  ->  "7000"  /  "7,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight (TW)`  vs  `Tongue Weight(TW)`
- categories: **1**  ·  peak reach: **2668**  ·  mean jaccard: 0.80  ·  max containment: 0.96
- shared values (sig -> forms):
    - `600 / 800`  ->  "600 LB - 800 LB"  /  "600 LB - 800 LB"
    - `400`  ->  "400 LBS"  /  "400 LB"
    - `900`  ->  "900 LBS"  /  "900 LB"
    - `600`  ->  "600 LBS"  /  "600 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Distribution`  vs  `Weight Distribution(WD)`
- categories: **1**  ·  peak reach: **2650**  ·  mean jaccard: 0.94  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LB"
    - `18000`  ->  "18000"  /  "18,000 LB"
    - `5500`  ->  "5500"  /  "5,500 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight (TW)`  vs  `WC Tongue Weight`
- categories: **1**  ·  peak reach: **2629**  ·  mean jaccard: 0.80  ·  max containment: 0.96
- shared values (sig -> forms):
    - `600 / 800`  ->  "600 LB - 800 LB"  /  "600  - 800"
    - `400`  ->  "400 LBS"  /  "400"
    - `900`  ->  "900 LBS"  /  "900"
    - `600`  ->  "600 LBS"  /  "600"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity (WC)`  vs  `Weight Carrying Capacity(WC)`
- categories: **1**  ·  peak reach: **2505**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17,000 LB"  /  "17,000 LB"
    - `2500`  ->  "2,500 LBS"  /  "2,500 LB"
    - `6000`  ->  "6,000 LBS"  /  "6,000 LB"
    - `7000`  ->  "7,000 LBS"  /  "7,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Carrying Capacity`  vs  `Weight Carrying Capacity (WC)`
- categories: **1**  ·  peak reach: **2485**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `2500`  ->  "2500"  /  "2,500 LBS"
    - `6000`  ->  "6000"  /  "6,000 LBS"
    - `7000`  ->  "7000"  /  "7,000 LBS"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Tongue Weight(TW)`  vs  `WD Tongue Weight`
- categories: **1**  ·  peak reach: **1820**  ·  mean jaccard: 0.40  ·  max containment: 0.71
- shared values (sig -> forms):
    - `500`  ->  "500 LB"  /  "500"
    - `400`  ->  "400 LB"  /  "400"
    - `2550`  ->  "2,550 LB"  /  "2550"
    - `900`  ->  "900 LB"  /  "900"
- in: Truck Equipment > Towing and Accessories > Hitches

### `WC Tongue Weight`  vs  `WD Tongue Weight`
- categories: **1**  ·  peak reach: **1781**  ·  mean jaccard: 0.40  ·  max containment: 0.71
- shared values (sig -> forms):
    - `500`  ->  "500"  /  "500"
    - `400`  ->  "400"  /  "400"
    - `2550`  ->  "2550"  /  "2550"
    - `900`  ->  "900"  /  "900"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Gross Trailer Weight(GTW)`
- categories: **1**  ·  peak reach: **1722**  ·  mean jaccard: 0.41  ·  max containment: 1.00
- shared values (sig -> forms):
    - `6000 / 8000`  ->  "6000 lbs. - 8000 lbs."  /  "6,000 LB - 8,000 LB"
    - `3500`  ->  "3500 lbs."  /  "3,500 LB"
    - `8000`  ->  "8000 lbs."  /  "8,000 LB"
    - `5000`  ->  "5000 lbs."  /  "5,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (lbs.)`  vs  `Gross Trailer Weight(GTW)`
- categories: **1**  ·  peak reach: **1710**  ·  mean jaccard: 0.41  ·  max containment: 1.00
- shared values (sig -> forms):
    - `6000 / 8000`  ->  "6000 - 8000"  /  "6,000 LB - 8,000 LB"
    - `3500`  ->  "3500"  /  "3,500 LB"
    - `8000`  ->  "8000"  /  "8,000 LB"
    - `5000`  ->  "5000"  /  "5,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight`  vs  `Gross Trailer Weight (GTW)`
- categories: **1**  ·  peak reach: **1699**  ·  mean jaccard: 0.43  ·  max containment: 0.92
- shared values (sig -> forms):
    - `6000 / 8000`  ->  "6000 lbs. - 8000 lbs."  /  "6,000 LB - 8,000 LB"
    - `7000`  ->  "7000 lbs."  /  "7,000 LB"
    - `3500`  ->  "3500 lbs."  /  "3,500 LBS"
    - `8000`  ->  "8000 lbs."  /  "8,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Gross Trailer Weight (GTW)`  vs  `Gross Trailer Weight (lbs.)`
- categories: **1**  ·  peak reach: **1687**  ·  mean jaccard: 0.43  ·  max containment: 0.92
- shared values (sig -> forms):
    - `6000 / 8000`  ->  "6,000 LB - 8,000 LB"  /  "6000 - 8000"
    - `7000`  ->  "7,000 LB"  /  "7000"
    - `3500`  ->  "3,500 LBS"  /  "3500"
    - `8000`  ->  "8,000 LB"  /  "8000"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Weight Distribution`  vs  `Weight Distribution (WD)`
- categories: **1**  ·  peak reach: **1647**  ·  mean jaccard: 0.94  ·  max containment: 1.00
- shared values (sig -> forms):
    - `17000`  ->  "17000"  /  "17,000 LB"
    - `12000`  ->  "12000"  /  "12,000 LBS"
    - `18000`  ->  "18000"  /  "18,000 LB"
    - `5500`  ->  "5500"  /  "5,500 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `SideStep Size`  vs  `SideStep Size (in.)`
- categories: **1**  ·  peak reach: **787**  ·  mean jaccard: 0.57  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4in"  /  "4"
    - `5`  ->  "5in"  /  "5"
    - `3`  ->  "3in"  /  "3"
    - `6`  ->  "6in"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Front Flare Tire Coverage`  vs  `Rear Flare Tire Coverage`
- categories: **1**  ·  peak reach: **675**  ·  mean jaccard: 0.48  ·  max containment: 0.78
- shared values (sig -> forms):
    - `0.8`  ->  "0.80"  /  "0.80"
    - `1.6`  ->  "1.60"  /  "1.60"
    - `4`  ->  "4.00"  /  "4.00"
    - `2.5`  ->  "2.50"  /  "2.50"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Air Filter Oulet Width`  vs  `Air Filter Outlet Width`
- categories: **1**  ·  peak reach: **499**  ·  mean jaccard: 0.56  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2.75 / 70`  ->  "2.750 in. (70mm)"  /  "2.750 in. (70mm)"
    - `0.625 / 16`  ->  "0.625 in. (16mm)"  /  "0.625 in. (16mm)"
- in: Truck Accessories > Air Intakes

### `Front Flare Tire Coverage`  vs  `Rear Flare Tire Coverage (inches)`
- categories: **1**  ·  peak reach: **438**  ·  mean jaccard: 0.46  ·  max containment: 0.95
- shared values (sig -> forms):
    - `4`  ->  "4.00"  /  "4"
    - `2.5`  ->  "2.50"  /  "2.5"
    - `1.5`  ->  "1.50"  /  "1.5"
    - `2.25`  ->  "2.25"  /  "2.25"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Front Flare Tire Coverage`  vs  `Front Flare Tire Coverage (inches)`
- categories: **1**  ·  peak reach: **424**  ·  mean jaccard: 0.53  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2.38`  ->  "2.38"  /  "2.38"
    - `4`  ->  "4.00"  /  "4"
    - `2.5`  ->  "2.50"  /  "2.5"
    - `1.5`  ->  "1.50"  /  "1.5"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Air Filter Outlet Length`  vs  `Air Filter Outlet Width`
- categories: **1**  ·  peak reach: **403**  ·  mean jaccard: 0.69  ·  max containment: 0.84
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2.75 / 70`  ->  "2.750 in. (70mm)"  /  "2.750 in. (70mm)"
    - `2 / 51`  ->  "2.000 in. (51mm)"  /  "2 in (51 mm)"
- in: Truck Accessories > Air Intakes

### `Front Flare Height`  vs  `Front Flare Height (inches)`
- categories: **1**  ·  peak reach: **383**  ·  mean jaccard: 0.57  ·  max containment: 0.91
- shared values (sig -> forms):
    - `7.5`  ->  "7.50"  /  "7.5"
    - `4`  ->  "4.00"  /  "4"
    - `2.5`  ->  "2.50"  /  "2.5"
    - `5.75`  ->  "5.75"  /  "5.75"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Rear Flare Height`  vs  `Rear Flare Height (inches)`
- categories: **1**  ·  peak reach: **366**  ·  mean jaccard: 0.57  ·  max containment: 0.92
- shared values (sig -> forms):
    - `7.5`  ->  "7.50"  /  "7.5"
    - `1.6`  ->  "1.60"  /  "1.6"
    - `4`  ->  "4.00"  /  "4"
    - `2.5`  ->  "2.50"  /  "2.5"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Height`  vs  `Height (in.)`
- categories: **1**  ·  peak reach: **355**  ·  mean jaccard: 0.47  ·  max containment: 0.74
- shared values (sig -> forms):
    - `1 / 25`  ->  "1 in (25 mm)"  /  "1.00 in. (25mm)"
    - `5.688 / 144`  ->  "5.688 in (144 mm)"  /  "5.688 in. (144 mm)"
    - `3.188 / 81`  ->  "3.188 in (81 mm)"  /  "3.188 in. (81 mm)"
    - `2.5 / 64`  ->  "2.5 in (64 mm)"  /  "2.50 in. (64mm)"
- in: Truck Accessories > Air Intakes

### `Air Filter Oulet Length`  vs  `Air Filter Outlet Length`
- categories: **1**  ·  peak reach: **308**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `1 / 25`  ->  "1.000 in. (25mm)"  /  "1.000 in. (25mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2 / 51`  ->  "2.000 in. (51mm)"  /  "2.000 in. (51mm)"
- in: Truck Accessories > Air Intakes

### `Bar Diameter`  vs  `Bar Diameter (in.)`
- categories: **1**  ·  peak reach: **243**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4" Oval"
    - `5`  ->  "5" Oval"  /  "5" Oval"
    - `6`  ->  "6" Oval"  /  "6" Oval"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Upper Mount Code`  vs  `Upper Mounting Code`
- categories: **1**  ·  peak reach: **207**  ·  mean jaccard: 0.59  ·  max containment: 0.90
- shared values (sig -> forms):
    - `29`  ->  "LS29"  /  "LS29"
    - `4`  ->  "XP4"  /  "XP4"
    - `28`  ->  "LS28"  /  "LS28"
    - `52`  ->  "LS52"  /  "LS52"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Avg Install Time`  vs  `Avg. Install Time`
- categories: **1**  ·  peak reach: **204**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `10 / 20`  ->  "10-20 Minutes"  /  "10-20 Minutes"
    - `5 / 10`  ->  "5-10 Minutes"  /  "5-10 Minutes"
- in: Truck Accessories > Truck Bed and Tailgate > Bed Mats

### `Lower Mounting Description`  vs  `Upper Mounting Description`
- categories: **1**  ·  peak reach: **177**  ·  mean jaccard: 0.57  ·  max containment: 0.77
- shared values (sig -> forms):
    - `2.5 / 8 / 1 / 2 / 13`  ->  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"  /  "Stem Mount - 2.5/8" Stem Length X 1/2"-13 Thread Pitch"
    - `12 / 1.5 / 8`  ->  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.5/8" Sleeve OAL"
    - `5 / 8 / 16 / 1.1 / 2`  ->  "Loop Bushing & Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 5/8"-16MM Sleeve ID X 1.1/2" Sleeve OAL"
    - `12 / 1.1 / 4`  ->  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"  /  "Loop Bushing & Sleeve Mount - 12MM Sleeve ID X 1.1/4" Sleeve OAL"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Front Flare Tire Coverage (inches)`  vs  `Rear Flare Tire Coverage (inches)`
- categories: **1**  ·  peak reach: **174**  ·  mean jaccard: 0.77  ·  max containment: 0.91
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2.5`  ->  "2.5"  /  "2.5"
    - `1.5`  ->  "1.5"  /  "1.5"
    - `2.25`  ->  "2.25"  /  "2.25"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Shank Size`  vs  `Shank Size (in)`
- categories: **1**  ·  peak reach: **162**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2""  /  "2"
    - `2.5`  ->  "2.5""  /  "2.5"
    - `3`  ->  "3""  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Lower Mounting Code`  vs  `Upper Mounting Code`
- categories: **1**  ·  peak reach: **156**  ·  mean jaccard: 0.41  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "XP4"  /  "XP4"
    - `2.625 / 0.5 / 13`  ->  "Stem Mount - 2.625 in. Stem Length x 0.500 in. -13"  /  "Stem Mount - 2.625 in. Stem Length x 0.500 in. -13"
    - `0.3125`  ->  "Cross Pin Mount - Open Ended 0.3125 in. Hole ID (B"  /  "Cross Pin Mount - Open Ended 0.3125 in. Hole ID (B"
    - `0.75 / 1.5625`  ->  "Loop Bushing Mount - 0.750 in. Bushing ID x 1.5625"  /  "Loop Bushing Mount - 0.750 in. Bushing ID x 1.5625"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Lower Mount Code`  vs  `Lower Mounting Code`
- categories: **1**  ·  peak reach: **142**  ·  mean jaccard: 0.51  ·  max containment: 0.89
- shared values (sig -> forms):
    - `81`  ->  "LS81"  /  "LS81"
    - `4`  ->  "XP4"  /  "XP4"
    - `48`  ->  "LS48"  /  "LS48"
    - `82`  ->  "LS82"  /  "LS82"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Intake Pipe Inlet Length`  vs  `Intake Pipe Inlet Width`
- categories: **1**  ·  peak reach: **115**  ·  mean jaccard: 0.43  ·  max containment: 0.98
- shared values (sig -> forms):
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `6 / 152`  ->  "6.000 in. (152mm)"  /  "6.000 in. (152mm)"
    - `2 / 51`  ->  "2 in (51 mm)"  /  "2 in (51 mm)"
    - `2.75 / 70`  ->  "2.75 in (70 mm)"  /  "2.750 in. (70mm)"
- in: Truck Accessories > Air Intakes

### `Gross Trailer Weight (GTW)`  vs  `Gross Trailer Weight(GTW)`
- categories: **1**  ·  peak reach: **71**  ·  mean jaccard: 0.71  ·  max containment: 0.91
- shared values (sig -> forms):
    - `6000 / 8000`  ->  "6,000 LB - 8,000 LB"  /  "6,000 LB - 8,000 LB"
    - `3500`  ->  "3,500 LBS"  /  "3,500 LB"
    - `8000`  ->  "8,000 LB"  /  "8,000 LB"
    - `5000`  ->  "5,000 LB"  /  "5,000 LB"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Intake Pipe Inlet Length`  vs  `Intake Pipe Outlet Length`
- categories: **1**  ·  peak reach: **55**  ·  mean jaccard: 0.64  ·  max containment: 0.99
- shared values (sig -> forms):
    - `15 / 381`  ->  "15.000 in. (381mm)"  /  "15.000 in. (381mm)"
    - `3.5 / 89`  ->  "3.500 in. (89mm)"  /  "3.500 in. (89mm)"
    - `2.75 / 70`  ->  "2.75 in (70 mm)"  /  "2.750 in. (70mm)"
    - `14.5 / 368`  ->  "14.500 in. (368mm)"  /  "14.500 in. (368mm)"
- in: Truck Accessories > Air Intakes

### `Diameter`  vs  `Diameter (IN)`
- categories: **1**  ·  peak reach: **52**  ·  mean jaccard: 0.45  ·  max containment: 0.71
- shared values (sig -> forms):
    - `9 / 16`  ->  "9/16"  /  "9/16 Inch"
    - `1 / 2`  ->  "1/2"  /  "1/2 Inch"
    - `1 / 4`  ->  "1/4 Inch"  /  "1/4 Inch"
    - `3 / 16`  ->  "3/16"  /  "3/16 Inch"
- in: Truck Equipment > Winches and Accessories

### `CARB/Air Horn Diameter`  vs  `CARB/Air Horn Diameter (in.)`
- categories: **1**  ·  peak reach: **42**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4.000 in."  /  "4.000 in."
    - `2.625`  ->  "2.625 in."  /  "2.625 in."
    - `4.25`  ->  "4.250 in."  /  "4.250 in."
    - `5`  ->  "5.000 in."  /  "5.000 in."
- in: Truck Accessories > Air Intakes

### `Line Diameter`  vs  `Pin Diameter`
- categories: **1**  ·  peak reach: **33**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "7"
    - `1`  ->  "1"  /  "1"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Winches and Accessories

### `Lift Height`  vs  `Lift_Height`
- categories: **1**  ·  peak reach: **32**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2 in"  /  "2"
    - `2.5`  ->  "2.5 in"  /  "2.5"
    - `1.5`  ->  "1.5"  /  "1.5"
    - `1.75`  ->  "1.75 in"  /  "1.75"
- in: Truck Accessories > Suspension > Leveling Kits

### `Board Length`  vs  `Board Length (in.)`
- categories: **1**  ·  peak reach: **21**  ·  mean jaccard: 0.70  ·  max containment: 1.00
- shared values (sig -> forms):
    - `72`  ->  "72 in."  /  "72"
    - `86`  ->  "86in"  /  "86"
    - `93`  ->  "93 in."  /  "93"
    - `46 / 97`  ->  "46in and 97in"  /  "46 and 97"
- in: Truck Accessories > Running Boards and Steps > Running Boards

### `Line Length`  vs  `Line Length (FT)`
- categories: **1**  ·  peak reach: **19**  ·  mean jaccard: 0.47  ·  max containment: 0.80
- shared values (sig -> forms):
    - `50`  ->  "50"  /  "50 Feet"
    - `60`  ->  "60"  /  "60 Feet"
    - `125`  ->  "125"  /  "125 Feet"
    - `100`  ->  "100"  /  "100 Feet"
- in: Truck Equipment > Winches and Accessories

### `Length`  vs  `Length (in.)`
- categories: **1**  ·  peak reach: **13**  ·  mean jaccard: 0.44  ·  max containment: 0.87
- shared values (sig -> forms):
    - `9.875 / 251`  ->  "9.875 in. (251mm)"  /  "9.875 in. (251 mm)"
    - `9.188 / 233`  ->  "9.188 in (233 mm)"  /  "9.188 in. (233 mm)"
    - `9.281 / 236`  ->  "9.281 in (236 mm)"  /  "9.281 in. (236 mm)"
    - `7.938 / 202`  ->  "7.938 in. (202mm)"  /  "7.938 in. (202 mm)"
- in: Truck Accessories > Air Intakes

### `Length`  vs  `Length (mm)`
- categories: **1**  ·  peak reach: **13**  ·  mean jaccard: 0.44  ·  max containment: 0.87
- shared values (sig -> forms):
    - `9.875 / 251`  ->  "9.875 in. (251mm)"  /  "9.875 in. (251 mm)"
    - `9.188 / 233`  ->  "9.188 in (233 mm)"  /  "9.188 in. (233 mm)"
    - `9.281 / 236`  ->  "9.281 in (236 mm)"  /  "9.281 in. (236 mm)"
    - `7.938 / 202`  ->  "7.938 in. (202mm)"  /  "7.938 in. (202 mm)"
- in: Truck Accessories > Air Intakes

### `Body Length`  vs  `Body Length (in.)`
- categories: **1**  ·  peak reach: **12**  ·  mean jaccard: 0.49  ·  max containment: 1.00
- shared values (sig -> forms):
    - `14.17`  ->  "14.17"  /  "14.170"
    - `16.69`  ->  "16.69"  /  "16.690"
    - `16.43`  ->  "16.43"  /  "16.430"
    - `10.78`  ->  "10.78"  /  "10.780"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts

### `Length (in.)`  vs  `Length (mm)`
- categories: **1**  ·  peak reach: **12**  ·  mean jaccard: 0.77  ·  max containment: 0.87
- shared values (sig -> forms):
    - `9.875 / 251`  ->  "9.875 in. (251 mm)"  /  "9.875 in. (251 mm)"
    - `9.188 / 233`  ->  "9.188 in. (233 mm)"  /  "9.188 in. (233 mm)"
    - `9.281 / 236`  ->  "9.281 in. (236 mm)"  /  "9.281 in. (236 mm)"
    - `7.938 / 202`  ->  "7.938 in. (202 mm)"  /  "7.938 in. (202 mm)"
- in: Truck Accessories > Air Intakes

### `TOTAL LENGTH`  vs  `Total Length`
- categories: **1**  ·  peak reach: **10**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `42`  ->  "42 IN"  /  "42 IN"
    - `25`  ->  "25 FT"  /  "25 FT"
    - `20`  ->  "20 FT"  /  "20 FT"
    - `48`  ->  "48 IN"  /  "48 IN"
- in: Truck Equipment > Towing and Accessories > Hitches

## LIKELY_FALSE - probably coincidental  (139)

### `Number Of Boxes`  vs  `Step Pad Quantity`
- categories: **3**  ·  peak reach: **3312**  ·  mean jaccard: 0.40  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Running Boards; Truck Accessories > Running Boards and Steps > Step Bars

### `Number of Pieces`  vs  `Sold As`
- categories: **3**  ·  peak reach: **2522**  ·  mean jaccard: 0.77  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Piece Set"
    - `1`  ->  "1"  /  "1 PC"
- in: Truck Accessories > Exterior > Bug and Hood Shields; Truck Accessories > Exterior > Side Window Deflectors; Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Min Year Covered`  vs  `Most Popular Year`
- categories: **3**  ·  peak reach: **197**  ·  mean jaccard: 0.46  ·  max containment: 0.94
- shared values (sig -> forms):
    - `2007`  ->  "2007"  /  "2007"
    - `2004`  ->  "2004"  /  "2004"
    - `2003`  ->  "2003"  /  "2003"
    - `2005`  ->  "2005"  /  "2005"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Leveling Kits; Truck Accessories > Suspension > Lift Kit Accessories

### `Max Year Covered`  vs  `Most Popular Year`
- categories: **3**  ·  peak reach: **193**  ·  mean jaccard: 0.55  ·  max containment: 0.90
- shared values (sig -> forms):
    - `2007`  ->  "2007"  /  "2007"
    - `2008`  ->  "2008"  /  "2008"
    - `2004`  ->  "2004"  /  "2004"
    - `2018`  ->  "2018"  /  "2018"
- in: Truck Accessories > Suspension > Coilover Shocks and Struts; Truck Accessories > Suspension > Lift Kit Accessories; Truck Accessories > Suspension > Shocks and Struts

### `Diameter`  vs  `Step Pad Quantity`
- categories: **2**  ·  peak reach: **3226**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Step Bars

### `Diameter`  vs  `Step Pad Surface Width`
- categories: **2**  ·  peak reach: **1085**  ·  mean jaccard: 0.42  ·  max containment: 1.00
- shared values (sig -> forms):
    - `6`  ->  "6"  /  "6""
    - `3`  ->  "3"  /  "3""
- in: Truck Accessories > Running Boards and Steps > Running Boards; Truck Accessories > Running Boards and Steps > Step Bars

### `Number of Pieces`  vs  `Package Quantity`
- categories: **2**  ·  peak reach: **854**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Piece Set"
    - `1`  ->  "1 pc."  /  "1 Pair"
    - `5`  ->  "5"  /  "5 Piece Set"
    - `3`  ->  "3"  /  "3 Piece Set"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners; Truck Accessories > Exterior > Fender Flares and Accessories

### `Number of Pieces`  vs  `WEB: Sold As`
- categories: **2**  ·  peak reach: **626**  ·  mean jaccard: 0.83  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Pc Set"
    - `2`  ->  "2"  /  "2 Pc Set"
- in: Truck Accessories > Exterior > Side Window Deflectors; Truck Accessories > Exterior > Fender Flares and Accessories

### `SideStep Size`  vs  `WEB: Size`
- categories: **2**  ·  peak reach: **600**  ·  mean jaccard: 0.58  ·  max containment: 1.00
- shared values (sig -> forms):
    - `5`  ->  "5in"  /  "5""
    - `6`  ->  "6in"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Running Boards; Truck Accessories > Running Boards and Steps > Step Bars

### `Diameter`  vs  `Surface Width`
- categories: **2**  ·  peak reach: **440**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "7""
    - `4`  ->  "4"  /  "4""
    - `6`  ->  "6"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Running Boards

### `Brackets per Side`  vs  `Number Of Boxes`
- categories: **2**  ·  peak reach: **406**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Running Boards

### `Brackets per Side`  vs  `Step Pad Quantity`
- categories: **2**  ·  peak reach: **310**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Running Boards and Steps > Powered Running Boards; Truck Accessories > Running Boards and Steps > Running Boards

### `Package Content`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **4414**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1CF"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Air Intakes

### `Flanges`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **4197**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1CF"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Number of Flanges`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **3596**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1CF"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Couplers Included`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **3508**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `1`  ->  "1"  /  "1CF"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Air Intakes

### `Filter Quantity`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **3130**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1CF"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `SideStep Size (in.)`  vs  `Step Pad Quantity`
- categories: **1**  ·  peak reach: **2773**  ·  mean jaccard: 0.60  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `6`  ->  "6"  /  "6"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Quantity`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **2649**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `6`  ->  "6"  /  "6""
    - `3`  ->  "3"  /  "3""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Quantity`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **2616**  ·  mean jaccard: 0.60  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `6`  ->  "6"  /  "6"
    - `3`  ->  "3"  /  "3.00"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Quantity`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **2586**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `6`  ->  "6"  /  "6""
    - `3`  ->  "3"  /  "3""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Flanges`  vs  `Package Content`
- categories: **1**  ·  peak reach: **2559**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Bar Diameter (in.)`  vs  `Step Pad Quantity`
- categories: **1**  ·  peak reach: **2554**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Class ID`  vs  `Hitch Class`
- categories: **1**  ·  peak reach: **2516**  ·  mean jaccard: 0.56  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Bar Diameter`  vs  `Step Pad Quantity`
- categories: **1**  ·  peak reach: **2479**  ·  mean jaccard: 0.40  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Depth`  vs  `Step Pad Quantity`
- categories: **1**  ·  peak reach: **2414**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Ball Mount Rise`  vs  `Class ID`
- categories: **1**  ·  peak reach: **2035**  ·  mean jaccard: 0.45  ·  max containment: 0.71
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `8`  ->  "8"  /  "8"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Class ID`  vs  `Drop Length`
- categories: **1**  ·  peak reach: **2026**  ·  mean jaccard: 0.55  ·  max containment: 0.75
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `8`  ->  "8"  /  "8"
    - `4`  ->  "4"  /  "4"
    - `10`  ->  "10"  /  "10"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Number of Flanges`  vs  `Package Content`
- categories: **1**  ·  peak reach: **1958**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Sold As`  vs  `WEB: Sold As`
- categories: **1**  ·  peak reach: **1911**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4-Piece"  /  "4 Pc Set"
    - `2`  ->  "2-Piece"  /  "2 Pc Set"
- in: Truck Accessories > Exterior > Side Window Deflectors

### `Couplers Included`  vs  `Package Content`
- categories: **1**  ·  peak reach: **1870**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Air Intakes

### `Attribute`  vs  `Sold As`
- categories: **1**  ·  peak reach: **1848**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4-piece"  /  "4 PC SET"
    - `1`  ->  "1-piece"  /  "1 PC REAR"
    - `2`  ->  "2-Piece"  /  "2 PC SET"
    - `3`  ->  "3-Piece"  /  "3 PC SET"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Floor Liner Piece Quantity`  vs  `Sold As`
- categories: **1**  ·  peak reach: **1763**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 PC SET"
    - `1`  ->  "1"  /  "1 PC REAR"
    - `2`  ->  "2"  /  "2 PC SET"
    - `3`  ->  "3"  /  "3 PC SET"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Piece Quantity`  vs  `Sold As`
- categories: **1**  ·  peak reach: **1763**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 PC SET"
    - `1`  ->  "1"  /  "1 PC REAR"
    - `2`  ->  "2"  /  "2 PC SET"
    - `3`  ->  "3"  /  "3 PC SET"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Package Quantity`  vs  `Sold As`
- categories: **1**  ·  peak reach: **1754**  ·  mean jaccard: 0.60  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4 Piece Set"  /  "4 PC SET"
    - `1`  ->  "1 Pair"  /  "1 PC REAR"
    - `3`  ->  "3 Piece Set"  /  "3 PC SET"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Flanges`  vs  `Number of Flanges`
- categories: **1**  ·  peak reach: **1741**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Kit Options`  vs  `Sold As`
- categories: **1**  ·  peak reach: **1721**  ·  mean jaccard: 0.43  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "Rear Only (4 pc) w/out Gap Hider"  /  "4 PC SET"
    - `2`  ->  "Front Only (2 pc)"  /  "2 PC SET"
    - `3`  ->  "Front Only (3 pc)"  /  "3 PC SET"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Filter Quantity`  vs  `Package Content`
- categories: **1**  ·  peak reach: **1492**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Package Content`  vs  `This Product Includes`
- categories: **1**  ·  peak reach: **1417**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 Filters"
    - `3`  ->  "3"  /  "3 Filters"
- in: Truck Accessories > Air Intakes

### `Filter Quantity`  vs  `Flanges`
- categories: **1**  ·  peak reach: **1275**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Diameter`  vs  `SideStep Size (in.)`
- categories: **1**  ·  peak reach: **1209**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Diameter`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **1052**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3.00"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Diameter`  vs  `Series`
- categories: **1**  ·  peak reach: **1051**  ·  mean jaccard: 0.40  ·  max containment: 0.75
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "R7 Running Boards"
    - `2`  ->  "2"  /  "SRX2 Side Steps"
    - `3`  ->  "3"  /  "V-Series V3 Side Steps"
    - `4`  ->  "4"  /  "Pro Traxx 4" Tube Steps"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Diameter`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **1022**  ·  mean jaccard: 0.44  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `5`  ->  "5"  /  "5""
    - `3`  ->  "3"  /  "3""
    - `6`  ->  "6"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter (in.)`  vs  `Diameter`
- categories: **1**  ·  peak reach: **990**  ·  mean jaccard: 0.56  ·  max containment: 0.83
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4" Oval"  /  "4"
    - `5`  ->  "5" Oval"  /  "5"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Installation Time`  vs  `Number Of Boxes`
- categories: **1**  ·  peak reach: **987**  ·  mean jaccard: 0.40  ·  max containment: 0.67
- shared values (sig -> forms):
    - `1`  ->  "1 Hour"  /  "1"
    - `2`  ->  "2 Hours"  /  "2"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Attribute`  vs  `Number of Pieces`
- categories: **1**  ·  peak reach: **948**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2-Piece"  /  "2 pc."
    - `3`  ->  "3-Piece"  /  "3"
    - `4`  ->  "4-piece"  /  "4"
    - `1`  ->  "1-piece"  /  "1 pc."
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Number Of Boxes`  vs  `Step Pad Depth`
- categories: **1**  ·  peak reach: **936**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Quantity of Balls included`  vs  `Receiver Size`
- categories: **1**  ·  peak reach: **868**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 inch"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Floor Liner Piece Quantity`  vs  `Number of Pieces`
- categories: **1**  ·  peak reach: **863**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2 pc."
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1 pc."
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Number of Pieces`  vs  `Piece Quantity`
- categories: **1**  ·  peak reach: **863**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2 pc."  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1 pc."  /  "1"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Diameter`  vs  `Step Pad Depth`
- categories: **1**  ·  peak reach: **850**  ·  mean jaccard: 0.44  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Kit Options`  vs  `Number of Pieces`
- categories: **1**  ·  peak reach: **821**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "Rear Only (4 pc) w/out Gap Hider"  /  "4"
    - `2`  ->  "Front Only (2 pc)"  /  "2 pc."
    - `5`  ->  "Rear Only (5 pc)"  /  "5"
    - `3`  ->  "Front Only (3 pc)"  /  "3"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Clamp Quantity`  vs  `Couplers Included`
- categories: **1**  ·  peak reach: **733**  ·  mean jaccard: 0.45  ·  max containment: 0.83
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1"
- in: Truck Accessories > Air Intakes

### `Filter Quantity`  vs  `Number of Flanges`
- categories: **1**  ·  peak reach: **674**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Air Intakes

### `Class Rating`  vs  `Hitch Class`
- categories: **1**  ·  peak reach: **656**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Hitch Class`  vs  `Quantity of Balls included`
- categories: **1**  ·  peak reach: **644**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Compatible Whale Tail Deck Option`  vs  `Door Quantity`
- categories: **1**  ·  peak reach: **638**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "CGWT-1"  /  "1"
    - `2`  ->  "CGWT-2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `SideStep Size (in.)`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **632**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `5`  ->  "5"  /  "5""
    - `3`  ->  "3"  /  "3""
    - `6`  ->  "6"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `SideStep Size`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **630**  ·  mean jaccard: 0.57  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4in"  /  "4"
    - `5`  ->  "5in"  /  "5"
    - `3`  ->  "3in"  /  "3.00"
    - `6`  ->  "6in"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Clamp Quantity`  vs  `Clamps Included`
- categories: **1**  ·  peak reach: **606**  ·  mean jaccard: 0.71  ·  max containment: 1.00
- shared values (sig -> forms):
    - `7`  ->  "7"  /  "7"
    - `2`  ->  "2"  /  "2"
    - `8`  ->  "8"  /  "8"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Air Intakes

### `SideStep Size (in.)`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **599**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3.00"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Hitch Class`  vs  `Number Of Hitch Balls Included`
- categories: **1**  ·  peak reach: **581**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Hitch Class`  vs  `Quantity of Pins included`
- categories: **1**  ·  peak reach: **575**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Equipment > Towing and Accessories > Hitches

### `SideStep Size (in.)`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **569**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `5`  ->  "5"  /  "5""
    - `3`  ->  "3"  /  "3""
    - `6`  ->  "6"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter (in.)`  vs  `SideStep Size`
- categories: **1**  ·  peak reach: **568**  ·  mean jaccard: 0.44  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4in"
    - `5`  ->  "5" Oval"  /  "5in"
    - `3`  ->  "3"  /  "3in"
    - `6`  ->  "6" Oval"  /  "6in"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter (in.)`  vs  `SideStep Size (in.)`
- categories: **1**  ·  peak reach: **537**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `5`  ->  "5" Oval"  /  "5"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Connector Style`  vs  `Output Type`
- categories: **1**  ·  peak reach: **537**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `7`  ->  "7 Blade"  /  "7-Way Round"
    - `4`  ->  "4 Flat"  /  "4-Way Flat"
    - `5`  ->  "5 Flat"  /  "5-Way Flat"
- in: Truck Equipment > Towing and Accessories > Hitch Wiring

### `Ball Mount Rise`  vs  `Hitch Class`
- categories: **1**  ·  peak reach: **509**  ·  mean jaccard: 0.50  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Coils Quantity Front`  vs  `Coils Quantity Rear`
- categories: **1**  ·  peak reach: **502**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `0`  ->  "0"  /  "0"
- in: Truck Accessories > Suspension > Lift Kit Accessories

### `Door Quantity`  vs  `Drawer Quantity`
- categories: **1**  ·  peak reach: **501**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `Bar Diameter`  vs  `SideStep Size`
- categories: **1**  ·  peak reach: **493**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4in"
    - `5`  ->  "5" Oval"  /  "5in"
    - `6`  ->  "6" Oval"  /  "6in"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Package Quantity`  vs  `WEB: Sold As`
- categories: **1**  ·  peak reach: **490**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4 Piece Set"  /  "4 Pc Set"
    - `2`  ->  "2 Piece Front"  /  "2 Pc Rear"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Door Quantity`  vs  `Latch Quantity`
- categories: **1**  ·  peak reach: **486**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `Step Pad Surface Width`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **475**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4""  /  "4"
    - `5`  ->  "5""  /  "5"
    - `3`  ->  "3""  /  "3.00"
    - `6`  ->  "6""  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter`  vs  `SideStep Size (in.)`
- categories: **1**  ·  peak reach: **462**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `5`  ->  "5" Oval"  /  "5"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Surface Width`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **445**  ·  mean jaccard: 0.67  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4""  /  "4""
    - `5`  ->  "5""  /  "5""
    - `3`  ->  "3""  /  "3""
    - `6`  ->  "6""  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Lug Hole Quantity`  vs  `Wheel Lug Hole Quantity`
- categories: **1**  ·  peak reach: **443**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `5`  ->  "5"  /  "5"
    - `8`  ->  "8"  /  "8"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Wheels and Tires

### `Lug Hole Quantity`  vs  `Spoke Quantity`
- categories: **1**  ·  peak reach: **429**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `5`  ->  "5"  /  "5"
    - `8`  ->  "8"  /  "8"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Wheels and Tires

### `Bar Diameter (in.)`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **413**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4""
    - `5`  ->  "5" Oval"  /  "5""
    - `3`  ->  "3"  /  "3""
    - `6`  ->  "6" Oval"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Tube Size`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **412**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `5`  ->  "5"  /  "5""
    - `3`  ->  "3.00"  /  "3""
    - `6`  ->  "6"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `SideStep Size (in.)`  vs  `Step Pad Depth`
- categories: **1**  ·  peak reach: **397**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `6`  ->  "6"  /  "6"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter (in.)`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **380**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `5`  ->  "5" Oval"  /  "5"
    - `3`  ->  "3"  /  "3.00"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter (in.)`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **350**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4""
    - `5`  ->  "5" Oval"  /  "5""
    - `3`  ->  "3"  /  "3""
    - `6`  ->  "6" Oval"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Package Quantity`  vs  `Rear Flare Width`
- categories: **1**  ·  peak reach: **346**  ·  mean jaccard: 0.40  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4 Piece Set"  /  "4"
    - `2`  ->  "2 Piece Front"  /  "2"
    - `1`  ->  "1 Set"  /  "1"
    - `6`  ->  "6 Piece Set"  /  "6"
- in: Truck Accessories > Exterior > Fender Flares and Accessories

### `Spoke Quantity`  vs  `Wheel Lug Hole Quantity`
- categories: **1**  ·  peak reach: **340**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `5`  ->  "5"  /  "5"
    - `8`  ->  "8"  /  "8"
    - `6`  ->  "6"  /  "6"
- in: Truck Accessories > Wheels and Tires

### `Bar Diameter`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **338**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4""
    - `5`  ->  "5" Oval"  /  "5""
    - `6`  ->  "6" Oval"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Bar Diameter`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **305**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `5`  ->  "5" Oval"  /  "5"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Qty of Balls included`  vs  `Quantity of Balls included`
- categories: **1**  ·  peak reach: **304**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Bar Diameter`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **275**  ·  mean jaccard: 0.60  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4""
    - `5`  ->  "5" Oval"  /  "5""
    - `6`  ->  "6" Oval"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Step Pad Depth`  vs  `Step Pad Surface Width`
- categories: **1**  ·  peak reach: **273**  ·  mean jaccard: 0.43  ·  max containment: 0.60
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `6`  ->  "6"  /  "6""
    - `3`  ->  "3"  /  "3""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Qty of Balls included`  vs  `Shank Size`
- categories: **1**  ·  peak reach: **249**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2""
    - `3`  ->  "3"  /  "3""
- in: Truck Equipment > Towing and Accessories > Hitches

### `Number Of Boxes`  vs  `Sub-category (Line)`
- categories: **1**  ·  peak reach: **246**  ·  mean jaccard: 0.40  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "RHINO! Charger RC2 - Complete kit: Front guard + Brackets"
    - `3`  ->  "3"  /  "RC3 LR w/Lights & Brackets"
- in: Truck Accessories > Bumpers and Grille Guards > Bull Bars

### `Compatible Whale Tail Deck Option`  vs  `Drawer Quantity`
- categories: **1**  ·  peak reach: **245**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "CGWT-1"  /  "1"
    - `2`  ->  "CGWT-2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `Quantity of Balls included`  vs  `Shank Size`
- categories: **1**  ·  peak reach: **243**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2""
    - `3`  ->  "3"  /  "3""
- in: Truck Equipment > Towing and Accessories > Hitches

### `Qty of Balls included`  vs  `Qty of Pins included`
- categories: **1**  ·  peak reach: **240**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `0`  ->  "0"  /  "0"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Step Pad Depth`  vs  `Tube Size`
- categories: **1**  ·  peak reach: **240**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `6`  ->  "6"  /  "6"
    - `3`  ->  "3"  /  "3.00"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Compatible Whale Tail Deck Option`  vs  `Latch Quantity`
- categories: **1**  ·  peak reach: **230**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "CGWT-1"  /  "1"
    - `2`  ->  "CGWT-2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `Lead Time AVG`  vs  `Quantity Sold`
- categories: **1**  ·  peak reach: **224**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1 Day"  /  "1"
    - `2`  ->  "2 Days"  /  "2"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Qty of Balls included`  vs  `Receiver Size (in)`
- categories: **1**  ·  peak reach: **223**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Qty of Balls included`  vs  `Shank Size (in)`
- categories: **1**  ·  peak reach: **223**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Quantity of Balls included`  vs  `Receiver Size (in)`
- categories: **1**  ·  peak reach: **217**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Quantity of Balls included`  vs  `Shank Size (in)`
- categories: **1**  ·  peak reach: **217**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Installation Level - 1 = Easy,   5 = Hard`  vs  `Installation Time (hrs)`
- categories: **1**  ·  peak reach: **217**  ·  mean jaccard: 0.57  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1 hrs"
    - `2`  ->  "2"  /  "2 hrs"
    - `3`  ->  "3"  /  "3"
- in: Van Equipment > Van Accessories

### `Step Pad Depth`  vs  `WEB: Size`
- categories: **1**  ·  peak reach: **210**  ·  mean jaccard: 0.43  ·  max containment: 0.60
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4""
    - `6`  ->  "6"  /  "6""
    - `3`  ->  "3"  /  "3""
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Lead Time AVG`  vs  `Lens Width`
- categories: **1**  ·  peak reach: **198**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1 Day"  /  "1""
    - `2`  ->  "2 Days"  /  "2""
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Attribute`  vs  `Floor Liner Piece Quantity`
- categories: **1**  ·  peak reach: **189**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2-Piece"  /  "2"
    - `3`  ->  "3-Piece"  /  "3"
    - `4`  ->  "4-piece"  /  "4"
    - `1`  ->  "1-piece"  /  "1"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Attribute`  vs  `Piece Quantity`
- categories: **1**  ·  peak reach: **189**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2-Piece"  /  "2"
    - `3`  ->  "3-Piece"  /  "3"
    - `4`  ->  "4-piece"  /  "4"
    - `1`  ->  "1-piece"  /  "1"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Attribute`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **180**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4-piece"  /  "4 Piece Set"
    - `1`  ->  "1-piece"  /  "1 Pair"
    - `5`  ->  "5-piece"  /  "5 Piece Set"
    - `3`  ->  "3-Piece"  /  "3 Piece Set"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Bar Diameter (in.)`  vs  `Step Pad Depth`
- categories: **1**  ·  peak reach: **178**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4" Oval"  /  "4"
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `6`  ->  "6" Oval"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Step Bars

### `Ball Mount Rise`  vs  `Class Rating`
- categories: **1**  ·  peak reach: **175**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Number Of Hitch Balls Included`  vs  `Qty of Pins included`
- categories: **1**  ·  peak reach: **171**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Number Of Hitch Balls Included`  vs  `Quantity of Pins included`
- categories: **1**  ·  peak reach: **166**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Qty of Pins included`  vs  `Quantity of Pins included`
- categories: **1**  ·  peak reach: **165**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Equipment > Towing and Accessories > Hitches

### `Attribute`  vs  `Kit Options`
- categories: **1**  ·  peak reach: **147**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4-piece"  /  "Rear Only (4 pc) w/out Gap Hider"
    - `2`  ->  "2-Piece"  /  "Front Only (2 pc)"
    - `5`  ->  "5-piece"  /  "Rear Only (5 pc)"
    - `3`  ->  "3-Piece"  /  "Front Only (3 pc)"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Mounting Hole Quantity`  vs  `Mounting Pattern Width`
- categories: **1**  ·  peak reach: **120**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4 Holes"  /  "4"
    - `2`  ->  "2 Holes"  /  "2"
- in: Truck Equipment > Winches and Accessories

### `Drive Gear`  vs  `Mounting Pattern Width`
- categories: **1**  ·  peak reach: **116**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4-Stage Planetary"  /  "4"
    - `2`  ->  "2-Stage Planetary"  /  "2"
    - `3`  ->  "3-Stage Planetary"  /  "3"
- in: Truck Equipment > Winches and Accessories

### `Number Of Boxes`  vs  `Product Line`
- categories: **1**  ·  peak reach: **116**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "Sport Bar 4.0"
    - `2`  ->  "2"  /  "Sport Bar 2.0 with Power Actuated Retractable Light Mount"
    - `3`  ->  "3"  /  "Sport Bar 3.0 (Mid Size)"
- in: Truck Accessories > Cargo Management > Truck and Van Racks

### `Body Style`  vs  `Sold As`
- categories: **1**  ·  peak reach: **112**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "SUV 4 DR"  /  "4 PC SET"
    - `2`  ->  "2 DOOR"  /  "2 PC SET"
- in: Truck Accessories > Exterior > Trim and Dress-Up Accessories

### `Floor Liner Piece Quantity`  vs  `Piece Quantity`
- categories: **1**  ·  peak reach: **104**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `3`  ->  "3"  /  "3"
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1"  /  "1"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Light Mount Quantity`  vs  `Number Of Boxes`
- categories: **1**  ·  peak reach: **96**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Cargo Management > Truck and Van Racks

### `Floor Liner Piece Quantity`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **95**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Piece Set"
    - `1`  ->  "1"  /  "1 Pair"
    - `5`  ->  "5"  /  "5 Piece Set"
    - `3`  ->  "3"  /  "3 Piece Set"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Package Quantity`  vs  `Piece Quantity`
- categories: **1**  ·  peak reach: **95**  ·  mean jaccard: 0.80  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4 Piece Set"  /  "4"
    - `1`  ->  "1 Pair"  /  "1"
    - `5`  ->  "5 Piece Set"  /  "5"
    - `3`  ->  "3 Piece Set"  /  "3"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Drawer Quantity`  vs  `Latch Quantity`
- categories: **1**  ·  peak reach: **93**  ·  mean jaccard: 1.00  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1"  /  "1"
    - `2`  ->  "2"  /  "2"
- in: Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories

### `SideStep Size`  vs  `Step Pad Quantity`
- categories: **1**  ·  peak reach: **86**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4in"  /  "4"
    - `6`  ->  "6in"  /  "6"
- in: Truck Accessories > Running Boards and Steps > Running Boards

### `Drive Gear`  vs  `Mounting Hole Quantity`
- categories: **1**  ·  peak reach: **84**  ·  mean jaccard: 0.40  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4-Stage Planetary"  /  "4 Holes"
    - `2`  ->  "2-Stage Planetary"  /  "2 Holes"
- in: Truck Equipment > Winches and Accessories

### `SideStep Size`  vs  `Surface Width`
- categories: **1**  ·  peak reach: **83**  ·  mean jaccard: 0.43  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4in"  /  "4""
    - `5`  ->  "5in"  /  "5""
    - `6`  ->  "6in"  /  "6""
- in: Truck Accessories > Running Boards and Steps > Running Boards

### `Floor Liner Piece Quantity`  vs  `Kit Options`
- categories: **1**  ·  peak reach: **62**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "Rear Only (4 pc) w/out Gap Hider"
    - `2`  ->  "2"  /  "Front Only (2 pc)"
    - `5`  ->  "5"  /  "Rear Only (5 pc)"
    - `3`  ->  "3"  /  "Front Only (3 pc)"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Kit Options`  vs  `Piece Quantity`
- categories: **1**  ·  peak reach: **62**  ·  mean jaccard: 0.57  ·  max containment: 0.80
- shared values (sig -> forms):
    - `4`  ->  "Rear Only (4 pc) w/out Gap Hider"  /  "4"
    - `2`  ->  "Front Only (2 pc)"  /  "2"
    - `5`  ->  "Rear Only (5 pc)"  /  "5"
    - `3`  ->  "Front Only (3 pc)"  /  "3"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `Light Mount Quantity`  vs  `Product Line`
- categories: **1**  ·  peak reach: **62**  ·  mean jaccard: 0.50  ·  max containment: 0.67
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "Sport Bar 4.0"
    - `3`  ->  "3"  /  "Sport Bar 3.0 (Mid Size)"
- in: Truck Accessories > Cargo Management > Truck and Van Racks

### `Installation Level - 1 = Easy,   5 = Hard`  vs  `Number Of Boxes`
- categories: **1**  ·  peak reach: **57**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `3`  ->  "3"  /  "3"
- in: Truck Accessories > Cargo Management > Cargo Racks

### `Installation Time (hrs)`  vs  `Number Of Boxes`
- categories: **1**  ·  peak reach: **54**  ·  mean jaccard: 0.75  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4"
    - `1`  ->  "1 hrs"  /  "1"
    - `2`  ->  "2 hrs"  /  "2"
- in: Truck Accessories > Cargo Management > Cargo Racks

### `Kit Options`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **53**  ·  mean jaccard: 0.43  ·  max containment: 0.75
- shared values (sig -> forms):
    - `4`  ->  "Rear Only (4 pc) w/out Gap Hider"  /  "4 Piece Set"
    - `5`  ->  "Rear Only (5 pc)"  /  "5 Piece Set"
    - `3`  ->  "Front Only (3 pc)"  /  "3 Piece Set"
- in: Truck Accessories > Interior > Floor Mats and Cargo Liners

### `SideStep Size`  vs  `Sub-category (Line)`
- categories: **1**  ·  peak reach: **52**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4in"  /  "4in OE Xtreme - Complete kit: Sidesteps + Brackets"
    - `5`  ->  "5in"  /  "5in OE Xtreme Low Profile - Complete kit: Sidesteps + Brackets"
    - `6`  ->  "6in"  /  "6in OE Xtreme Wheel to Wheel"
- in: Truck Accessories > Running Boards and Steps > Running Boards

### `Lens Width`  vs  `Quantity Sold`
- categories: **1**  ·  peak reach: **44**  ·  mean jaccard: 0.40  ·  max containment: 1.00
- shared values (sig -> forms):
    - `1`  ->  "1""  /  "1"
    - `2`  ->  "2""  /  "2"
- in: Truck Accessories > Automotive Lighting > LED Auxiliary Lights

### `Install Time`  vs  `Number Of Boxes`
- categories: **1**  ·  peak reach: **43**  ·  mean jaccard: 0.50  ·  max containment: 0.75
- shared values (sig -> forms):
    - `1`  ->  "Less than 1 hour"  /  "1"
    - `2`  ->  "2+ Hours"  /  "2"
    - `3`  ->  "3+ Hours"  /  "3"
- in: Truck Accessories > Cargo Management > Cargo Racks

### `Number Of Boxes`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **37**  ·  mean jaccard: 0.50  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Piece Set"
    - `1`  ->  "1"  /  "1 Pair"
- in: Truck Accessories > Cargo Management > Cargo Racks

### `Installation Time (hrs)`  vs  `Package Quantity`
- categories: **1**  ·  peak reach: **33**  ·  mean jaccard: 0.67  ·  max containment: 1.00
- shared values (sig -> forms):
    - `4`  ->  "4"  /  "4 Piece Set"
    - `1`  ->  "1 hrs"  /  "1 Pair"
- in: Truck Accessories > Cargo Management > Cargo Racks

### `Ball Mount Rise`  vs  `Drop Length`
- categories: **1**  ·  peak reach: **19**  ·  mean jaccard: 0.50  ·  max containment: 0.71
- shared values (sig -> forms):
    - `2`  ->  "2"  /  "2"
    - `8`  ->  "8"  /  "8"
    - `4`  ->  "4"  /  "4"
    - `5`  ->  "5"  /  "5"
- in: Truck Equipment > Towing and Accessories > Hitches
