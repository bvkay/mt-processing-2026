# Morocco field sheets reconciled with the site tables

2026-09-25. Sources: 101 transcribed half-sheets and PDF pages (85 from photos in `Field_Notes`, 16 from `Deployment sheet A16-A31.pdf`), the B423 header table (`survey_yaml_sites.csv`), `Morocco_LEMInew2025.csv`, the two 2023 tables and the 2023 timing sheet. survey.yaml and the other tracked files were not changed; the new files are `site_table_field_notes.csv` (next to this report) and `D:/MT_DATA/MT_Morocco_Atlas_Mountains_Workspace/field_notes/transcripts/all_sheets.json`.

Revised after a second reading. All 42 high-severity discrepancies were re-read against the photos by a reader working from zoomed, rotated crops and trying to prove the transcription wrong. 37 transcriptions stood and 5 were refuted. The corrections are in the site table and in this report; `all_sheets.json` keeps the original transcriptions. The site table has a new last column, `verified`, naming the fields that were re-read and what the re-read found.

## What matters most

1. **Line B dipoles are mostly defaults.** survey.yaml carries 50/50 m for B01, B02, B07, B10, B13-B15, B19-B21, B26, B27 and B29, 52.8/53.5 for B28, and nothing for B24/B25. The re-read confirmed every contested line-B cell. Seven sites are wrong or empty whichever way the cells are read: B20 (Ex 21-23 m), B21 (27-29 / 25-27 m), B19 (35-39 / 25-29 m), B24 (33-35 / 34-36 m), B25 (32-32.5 / 16-18 m), B28 (Ey 30-33.5 m, not 53.5; the Ey/E cell is a clear 30) and B07 (Ey 38-43 m). Apparent resistivity there is off by factors of 1.4 to 10. At the other line-B sites the only question is 50 m against 53-55 m. That turns on whether the two arms add, which moves rho by 17 % at most (see Dipoles).
2. **A05 is not A05.** The survey.yaml A05 header and the A05 folder are copies of A14 (same position, serial 12, same file checksums). The A-5 sheet puts A5 at 31.3407 N, 9.7134 W with logger 11 on 13 or 14 July (13 overwritten to 14; re-read confirmed). That recording is not in the archive.
3. **A22 exists on paper but not in the survey.** The AM-A22 form (pdf p7), the 2023 tables and the timing sheet all show A22 (26 Feb-1 Mar 2023, logger 8). survey.yaml has no A22 and there is no A22 folder.
4. **A24 azimuth_ey = 241 is a column shift.** The coil serials 241/243 slid into the azimuth columns of the tables and from there into survey.yaml. Ey should be 90. The re-read confirmed that the sheet has Bx 241, By 243 and no azimuth anywhere.
5. **Three sheet positions are wrong, not the loggers:** A04 (7.79 for 7.72, 6.6 km), A09 (copied from A8, 5.4 km) and A05 (see 2). The B19 outlier was a misreading: its latitude is 31.247844, 4 m from the logger. Every other sheet lies within 200 m of its logger GPS, most within 10 m.
6. **B30/B31 have no field evidence of their own.** Every sheet whose Site line says B30 or B31 has the same date, position, logger and coils as B28/B29. B12 was deployed on 22 July and marked "A refaire" (to be redone); B22 and B23 have no sheet at all.

The discrepancy list has 65 entries, 42 of them high severity. Most of the high ones are the dipole defaults in item 1. All 42 were re-read: 37 stood and are genuine disagreements for Ben, and 5 were refuted (A12 Ex/N, the B16 logger, the B19 latitude and two B26 dipole claims). The 23 low-severity entries were not re-read, though the re-readers read several of their values in passing.

## Coverage

- 101 records: 99 mapped to 59 sites, 2 unmatched. Many pages were photographed two to four times, so most sites have several records of the same form.
- **Sites with a sheet (59):** A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A16, A17, A18, A19, A20, A21, A22, A23, A24, A25, A26, A27, A28, A29, A30, A31, B01, B02, B03, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, B14, B15, B16, B17, B18, B19, B20, B21, B24, B25, B26, B27, B28, B29, R05.
- **Sites with no sheet:** B30, B31, C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21, C21new, C22, C23, D01, D02, D03, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, R01, R02, R03, R04, R06. B22 and B23 have neither data nor a sheet. Line C, line D and the February, March and September remote deployments (R01-R04, R06) have no forms in `Field_Notes`. The only remote form is a July one. B30/B31 are covered by the B28/B29 forms (see below).
- **Unmatched records:**
  - IMG_1873_2.jpg upper: out of focus (legibility 0.15): no readable site code, date or coordinates. The few shapes that can be made out (Area like B.1?, latitude like 31.7102, coils 24x, N-G 36,6 mV, arms 50/3/3/50) match IMG_1201_2 upper (B10) value for value, so it is most likely a blurred second photo of that page; not used
  - IMG_1873_2.jpg lower: out of focus (legibility 0.3): no readable site code, date or coordinates. The legible values (A refaire !!, 11h:44, arms 5/45/35/3, battery 12.85, N-G 0.9 kOhm, 34.6 mV) match IMG_1201_2 lower (B12, Dar Soulaimani) value for value, so it is most likely a blurred second photo of that page; not used. Its By reading 116 differs from 126 on IMG_1201_2
- **Half-sheet labels.** `upper` and `lower` in `source_photo` give the half-sheet's place in the JPG as stored. Most pages were photographed sideways, so once turned upright the two half-sheets sit side by side. The re-readers identified each half-sheet by its site fields, not by the label.
- **How sheets were mapped.** First by the site code on the sheet: the page-corner code, then the Area field, then the Site line. A code was overridden only when the sheet position was more than 500 m from that site but within 500 m of another header whose serial matched the sheet logger. This happened once, for Targa (B24). Sheets without a usable code were mapped by position: AA3 to A13, A1? to A15 and B2? to B21. Two were mapped by matching values: the curled AA5 half-sheet to A15 and the cropped A29 form on IMG_1476_2. The Remote form went to R05, the only July remote deployment, despite its date (see the discrepancy list).

## Dipoles

Sheet totals are the sums of the two arms (Ex = Ex/N + Ex/S, Ey = Ey/E + Ey/W). The factor is (current / sheet)^2, the multiplier on apparent resistivity when the sheet length replaces the current one. f_xy applies to rho_xy (Ex) and f_yx to rho_yx (Ey). "-" means the sheet gives no usable total, and the reason is in the site table notes. Every arm reading behind a flagged line-B row was re-read and stands. The 2025 column is the `Morocco_LEMInew2025.csv` row at the same position. For March line B that row has a different name (2025 B26-B31 = survey B24-B29).

| site | arms N/S/E/W (m) | sheet Ex | sheet Ey | survey.yaml Ex/Ey | 2025 Ex/Ey | f_xy | f_yx | flag |
|---|---|---|---|---|---|---|---|---|
| A01 | 50 / 50 / 5 / 4 | - | - | 55/54 | 55/54 | - | - |  |
| A02 | 2 / 40 or 50 / 46 / 2 | - | 48 | 42/48 | 42/48 | - | 1.00 |  |
| A03 | 4 / 50 / 50 / 3 | 54 | 53 | 54/53 | 54/53 | 1.00 | 1.00 |  |
| A04 | 50 / 3 / 2 / 50 | 53 | 52 | 53/52 | 53/52 | 1.00 | 1.00 |  |
| A05 | 50 / 5 / 5 / 51 | 55 | 56 | 55/56 | 55/56 | 1.00 | 1.00 |  |
| A06 | 50 / 4 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| A07 | 2 / 50 / 50 / 2 | 52 | 52 | 52/52 | 52/52 | 1.00 | 1.00 |  |
| A08 | 4 / 41 / 5 / 47 | 45 | 52 | 45/52 | 45/52 | 1.00 | 1.00 |  |
| A09 | 44 / 4.5 / 4 / 41 | 48.5 | 45 | 48.5/45 | 48.5/45 | 1.00 | 1.00 |  |
| A10 | 50 / 4 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| A11 | 5 / 38 / 50 / 4 | 43 | 54 | 43/54 | 43/54 | 1.00 | 1.00 |  |
| A12 | 50 / 3 / 50 / 3 or 4 | 53 | 53 or 54 | 53/54 | 53/54 | 1.00 | - |  |
| A13 | 3 / 50 / 50 / 3 | 53 | 53 | 53/53 | 53/53 | 1.00 | 1.00 |  |
| A14 | 50 / 4 / 49 / 4 | 54 | 53 | 54/53 | 54/53 | 1.00 | 1.00 |  |
| A15 | 50 / 4 / 1 / 50 | 54 | 51 | 54/51 | 54/51 | 1.00 | 1.00 |  |
| A16 | 50 / 4 / 47 / 1 | 54 | 48 | 54/48 | 54/48 | 1.00 | 1.00 |  |
| A17 | 44 / 4.5 / 4.2 / 50 | 48.5 | 54.2 | 48.5/54.2 | 48.5/54.2 | 1.00 | 1.00 |  |
| A18 | 3 / 50 / 50 / 3 | 53 | 53 | 53/53 | 53/53 | 1.00 | 1.00 |  |
| A19 | 47 / 5 / 3 / 39 | 52 | 42 | 52/42 | 52/42 | 1.00 | 1.00 |  |
| A20 | 4 / 50 / 4 / 50 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| A21 | 44 / 2.5 / 50 / 2.5 | 46.5 | 52.5 | 46.5/52.5 | 46.5/52.5 | 1.00 | 1.00 |  |
| A22 | 46 / 3 / 50 / 2.5 | 49 | 52.5 | -/- | - | - | - | new |
| A23 | 46 / ?,5 / 47 / 4.2 | - | 51.2 | 50.5/51.2 | 50.5/51.2 | - | 1.00 |  |
| A24 | 3.5 / 48 / 35 / 3.5 | 51.5 | 38.5 | 51.5/38.5 | 51.5/38.5 | 1.00 | 1.00 |  |
| A25 | 4 / 50 / 50 / 5 | 54 | 55 | 54/55 | 54/55 | 1.00 | 1.00 |  |
| A26 | 50 / 4 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| A27 | 50 / 4 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| A28 | 4 / 50 / 2 / 50 | 54 | 52 | 54/52 | 54/52 | 1.00 | 1.00 |  |
| A29 | 50 / 4 / 44 / 1 | 54 | 45 | 54/45 | 54/45 | 1.00 | 1.00 |  |
| A30 | 50 / 1 / 49 / 3 | 51 | 52 | 51/52 | 51/52 | 1.00 | 1.00 |  |
| A31 | 43 / 5 / 4.5 / 42 | 48 | 46.5 | 48/46.5 | 48/46.5 | 1.00 | 1.00 |  |
| B01 | 4 / 50 / 4 / 50 | 54 | 54 | 50/50 | 50/50 | 0.86 | 0.86 | Ex Ey |
| B02 | 4.9 / 50 / 4 / 50 | 54.9 | 54 | 50/50 | 50/50 | 0.83 | 0.86 | Ex Ey |
| B03 | 50 / 3 / 50 / 3 | 53 | 53 | 53/53 | 53/53 | 1.00 | 1.00 |  |
| B04 | 50 / 3 / 50 / 3 | 53 | 53 | 53/53 | 53/53 | 1.00 | 1.00 |  |
| B05 | 4 / 50 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| B06 | 44 / 4 / 50 / 4 | 48 | 54 | 48/54 | 48/54 | 1.00 | 1.00 |  |
| B07 | 50 / 2 / 5 / 38 | 52 | 43 | 50/50 | 50/50 | 0.92 | 1.35 | Ex Ey |
| B08 | 50 / 4 / 50 / 4 | 54 | 54 | 54/54 | 54/54 | 1.00 | 1.00 |  |
| B09 | 37 / 5 / 50 / 1 | 42 | 51 | 42/51 | 42/51 | 1.00 | 1.00 |  |
| B10 | 50 / 3 / 3 / 50 | 53 | 53 | 50/50 | 50/50 | 0.89 | 0.89 | Ex Ey |
| B11 | 41 / 4 / 3 / 50 | 45 | 53 | 45/53 | 45/53 | 1.00 | 1.00 |  |
| B12 | 5 / 45 / 35 / 3 | 50 | 38 | -/- | - | - | - | new |
| B13 | 50 / 3 / 50 / 5 | 53 | 55 | 50/50 | 50/50 | 0.89 | 0.83 | Ex Ey |
| B14 | 50 / 3 / 3 / 50 | 53 | 53 | 50/50 | 50/50 | 0.89 | 0.89 | Ex Ey |
| B15 | 50 / 4 / 50 / 3 | 54 | 53 | 50/50 | 50/50 | 0.86 | 0.89 | Ex Ey |
| B16 | 40 / 2 / 47 / 3 | 42 | 50 | 42/50 | 42/50 | 1.00 | 1.00 |  |
| B17 | 36 / 2 / 39 / 2 | 38 | 41 | 38/41 | 38/41 | 1.00 | 1.00 |  |
| B18 | 47 / 4 / 50 / 2.5 | 51 | 52.5 | 51/52.5 | 51/52.5 | 1.00 | 1.00 |  |
| B19 | 35 / 4 / 4 / 25 | 39 | 29 | 50/50 | 50/50 | 1.64 | 2.97 | Ex Ey |
| B20 | 21 / 2 / 50 / 2 | 23 | 52 | 50/50 | 50/50 | 4.73 | 0.92 | Ex Ey |
| B21 | 27 / 2 / 25 / 2 | 29 | 27 | 50/50 | 50/50 | 2.97 | 3.43 | Ex Ey |
| B24 | 2 / 33 / 34 / 2 | 35 | 36 | -/- | 50/50 | - | - | new |
| B25 | 32 / 0.5 / 2 / 16 | 32.5 | 18 | -/- | 50/50 | - | - | new |
| B26 | 50 / ? / 50 / 3 | - | 53 | 50/50 | 52.8/53.5 | - | 0.89 | Ey |
| B27 | 47 / 1 / 50 / 3 | 48 | 53 | 50/50 | 50/50 | 1.09 | 0.89 | Ex Ey |
| B28 | 50 / 2.8 / 30 / 3.5 | 52.8 | 33.5 | 52.8/53.5 | 50/50 | 1.00 | 2.55 | Ey |
| B29 | 50 / 4 / 44 / 4.5 | 54 | 48.5 | 50/50 | 50/50 | 0.86 | 1.06 | Ex Ey |
| R05 | 2 / 3 / 50 / 50 | - | - | 50/50 | 50/50 | - | - |  |

**Where the change exceeds 5 %** (or where survey.yaml has no length):

- A22: Ex 49 m (survey.yaml empty); Ey 52.5 m (survey.yaml empty)
- B01: Ex 50 -> 54 m (rho_xy x0.86); Ey 50 -> 54 m (rho_yx x0.86)
- B02: Ex 50 -> 54.9 m (rho_xy x0.83); Ey 50 -> 54 m (rho_yx x0.86)
- B07: Ex 50 -> 52 m (rho_xy x0.92); Ey 50 -> 43 m (rho_yx x1.35)
- B10: Ex 50 -> 53 m (rho_xy x0.89); Ey 50 -> 53 m (rho_yx x0.89)
- B12: Ex 50 m (survey.yaml empty); Ey 38 m (survey.yaml empty)
- B13: Ex 50 -> 53 m (rho_xy x0.89); Ey 50 -> 55 m (rho_yx x0.83)
- B14: Ex 50 -> 53 m (rho_xy x0.89); Ey 50 -> 53 m (rho_yx x0.89)
- B15: Ex 50 -> 54 m (rho_xy x0.86); Ey 50 -> 53 m (rho_yx x0.89)
- B19: Ex 50 -> 39 m (rho_xy x1.64); Ey 50 -> 29 m (rho_yx x2.97)
- B20: Ex 50 -> 23 m (rho_xy x4.73); Ey 50 -> 52 m (rho_yx x0.92)
- B21: Ex 50 -> 29 m (rho_xy x2.97); Ey 50 -> 27 m (rho_yx x3.43)
- B24: Ex 35 m (survey.yaml empty); Ey 36 m (survey.yaml empty)
- B25: Ex 32.5 m (survey.yaml empty); Ey 18 m (survey.yaml empty)
- B26: Ey 50 -> 53 m (rho_yx x0.89)
- B27: Ex 50 -> 48 m (rho_xy x1.09); Ey 50 -> 53 m (rho_yx x0.89)
- B28: Ey 53.5 -> 33.5 m (rho_yx x2.55)
- B29: Ex 50 -> 54 m (rho_xy x0.86); Ey 50 -> 48.5 m (rho_yx x1.06)

Line A agrees with survey.yaml at every site where the sheet is readable (A12 now included: its Ex/N is 50, not 60), so line A was evidently entered from these forms. Line B was partly entered (B03-B06, B08, B09, B11, B16-B18 agree) and partly left at 50/50. Sites with no usable sheet total: A01 (cells read 50/50/5/4 on both photos; survey.yaml 55/54 is a plausible repair), A02 Ex (Ex/S is a 50 with a later 4 written over the 5, so 42 m is likely, as in survey.yaml), A12 Ey (Ey/W a 3 and a 4 overlaid, 53 or 54 m), A23 Ex (Ex/S blotted), B26 Ex (Ex/S blank on all three photos) and R05 (cells read 2/3/50/50).

### Do the arms add?

The re-read settled the digits. It did not settle what they mean, and the re-readers disagreed about it. Every totals column above assumes the two cells on a line are arm lengths from the logger, so that the dipole is their sum. Some re-readers (FN011-FN013, FN027, FN036, FN040, FN041) think the long cell may hold the whole dipole and the short cell an offset. In that case the dipole is the long cell alone.

**The big line-B errors hold under both readings:**

| site | comp | cells | arms added | long cell only | survey.yaml | rho factor (added / long only) |
|---|---|---|---|---|---|---|
| B07 | Ey | 5 + 38 | 43 | 38 | 50 | 1.35 / 1.73 |
| B19 | Ex | 35 + 4 | 39 | 35 | 50 | 1.64 / 2.04 |
| B19 | Ey | 4 + 25 | 29 | 25 | 50 | 2.97 / 4.00 |
| B20 | Ex | 21 + 2 | 23 | 21 | 50 | 4.73 / 5.67 |
| B21 | Ex | 27 + 2 | 29 | 27 | 50 | 2.97 / 3.43 |
| B21 | Ey | 25 + 2 | 27 | 25 | 50 | 3.43 / 4.00 |
| B24 | Ex | 2 + 33 | 35 | 33 | empty (2025: 50) | 2.04 / 2.30 against 50 |
| B24 | Ey | 34 + 2 | 36 | 34 | empty (2025: 50) | 1.93 / 2.16 against 50 |
| B25 | Ex | 32 + 0.5 | 32.5 | 32 | empty (2025: 50) | 2.37 / 2.44 against 50 |
| B25 | Ey | 2 + 16 | 18 | 16 | empty (2025: 50) | 7.72 / 9.77 against 50 |
| B28 | Ey | 30 + 3.5 | 33.5 | 30 | 53.5 | 2.55 / 3.18 |

**The small ones depend on the reading.** At B01, B02, B07 (Ex), B10, B13-B15, B20 (Ey), B26 (Ey), B27 (Ey) and B29 (Ex), adding the arms gives 52-55 m and rho x0.83-0.92. Taking the long cell alone gives 50 m, which means survey.yaml is right there. B27 Ex (47 + 1) and B29 Ey (44 + 4.5) fall below 50 m either way, by 4-12 %. The same question applies in reverse to line A and to B03-B06, B08, B09, B11 and B16-B18, where survey.yaml already adds the arms. If the long cell alone is the dipole, those values are 4-10 % too long.

**Adding the arms is more likely:**
- The form asks for arm lengths: its cells are headed Ex/N (m), Ex/S (m), Ey/E (m) and Ey/W (m).
- The re-readers checked the mud maps at A01, B01, B10, B13, B14, B15, B21, B25, B28 and B29. Each draws the logger off centre, with a long and a short arm on each line. Where the sides can be told, they match the grid, except the Ey line at B10 (short arm drawn on the W, written on the E) and A01, where the map is what suggests the cells were written under the wrong headings. The maps that do not show an offset are B02 (a symmetric cross) and B20 (both lines running well out on each side). None is to scale.
- The long cell changes side from site to site (Ex/N at A04, Ex/S at A03; Ey/E at A03, Ey/W at A04). That fits a logger placed near one electrode. It does not fit a habit of writing the whole dipole in a particular box.
- Whoever built the 2025 table added the arms at about 40 sites.

Against it: nearly every site has one arm of 0.5-5 m, the B26 Ex/S cell is blank, and two sheets (A01, R05) make no sense under either reading.

One fact settles it: how the crews ran the cables. Was the logger beside one electrode with a long cable to the other? The kit's cable lengths would answer that too.

A data check can only catch the large factors. A wrong length on one line splits rho_xy from rho_yx by the ratio of the two factors: about x5 at B20, x3.3 at B25, x2.6 at B28 and x1.8 at B19. At the shortest periods the two curves are often close, so rescaling should shrink the split there. The check fails if rescaling widens it. Static shift also splits curves, often by x2-3, so only B20 and B25 give a clear test. B21 and B24 scale both lines about equally and can only be compared with their neighbours. No data check can tell 50 m from 54 m.

## Positions

Distance from the sheet position to the B423 header (logger GPS). Where a site has several readable sheets, the most legible one is used.

| site | sheet lat, lon | header lat, lon | distance (m) |
|---|---|---|---|
| A01 | 31.540442, -9.686416 | 31.540402, -9.686461 | 6 |
| A02 | 31.455565, -9.776560 | 31.455528, -9.776493 | 8 |
| A03 | 31.412172, -9.694386 | 31.412221, -9.694349 | 6 |
| A04 | 31.368237, -9.792675 | 31.368264, -9.722686 | 6645 ** |
| A05 | 31.340706, -9.713373 | 30.917771, -9.586553 | 48553 ** |
| A06 | 31.286893, -9.719882 | 31.288688, -9.719865 | 200 |
| A07 | 31.254701, -9.722106 | 31.254740, -9.722028 | 9 |
| A08 | 31.200905, -9.698156 | 31.200901, -9.698134 | 2 |
| A09 | 31.200905, -9.698156 | 31.167268, -9.657706 | 5366 ** |
| A10 | 31.112577, -9.638103 | 31.112570, -9.638101 | 1 |
| A11 | 31.068461, -9.575408 | 31.068498, -9.575394 | 4 |
| A12 | 31.009934, -9.576395 | 31.009696, -9.575538 | 86 |
| A13 | 30.968954, -9.570477 | 30.968943, -9.570451 | 3 |
| A14 | 30.917829, -9.586551 | 30.917771, -9.586553 | 6 |
| A15 | 30.887404, -9.605124 | 30.887369, -9.605093 | 5 |
| A16 | 30.833570, -9.602080 | 30.833687, -9.602112 | 13 |
| A17 | 30.771320, -9.565840 | 30.771295, -9.565879 | 5 |
| A18 | 30.720810, -9.550020 | 30.720850, -9.550004 | 5 |
| A19 | 30.675860, -9.478440 | 30.675930, -9.478464 | 8 |
| A20 | 30.622500, -9.488970 | 30.622522, -9.489000 | 4 |
| A21 | 30.596085, -9.518618 | 30.596115, -9.518619 | 3 |
| A23 | 30.514760, -9.595150 | 30.514738, -9.595178 | 4 |
| A24 | 30.485060, -9.558760 | 30.485076, -9.558814 | 5 |
| A25 | 30.443900, -9.552880 | 30.443924, -9.552920 | 5 |
| A26 | 30.409980, -9.511130 | 30.409971, -9.511137 | 1 |
| A27 | 30.369080, -9.490640 | 30.369069, -9.490649 | 1 |
| A28 | 30.314790, -9.463880 | 30.314837, -9.463860 | 6 |
| A29 | 30.279870, -9.446370 | 30.279858, -9.446402 | 3 |
| A30 | 30.255830, -9.424870 | 30.255815, -9.424831 | 4 |
| A31 | 30.201860, -9.388730 | 30.201844, -9.388719 | 2 |
| B01 | 32.105528, -7.964559 | 32.105506, -7.964529 | 4 |
| B02 | 32.050942, -7.953253 | 32.050941, -7.953259 | 1 |
| B03 | 32.023354, -7.946479 | 32.023322, -7.946535 | 6 |
| B05 | 31.926312, -7.936805 | 31.926319, -7.936793 | 1 |
| B06 | 31.874218, -7.929317 | 31.874208, -7.929313 | 1 |
| B08 | 31.793174, -7.975328 | 31.793169, -7.975344 | 2 |
| B09 | 31.756244, -7.977594 | 31.756279, -7.977600 | 4 |
| B10 | 31.710240, -7.950985 | 31.710256, -7.950965 | 3 |
| B11 | 31.650944, -7.948277 | 31.650964, -7.948485 | 20 |
| B13 | 31.536359, -7.994886 | 31.536346, -7.994887 | 1 |
| B14 | 31.464171, -7.987536 | 31.464129, -7.987555 | 5 |
| B15 | 31.426031, -7.959800 | 31.426023, -7.959777 | 2 |
| B16 | 31.372565, -7.950495 | 31.372618, -7.950477 | 6 |
| B17 | 31.328343, -7.947505 | 31.328269, -7.945723 | 169 |
| B18 | 31.300484, -7.995398 | 31.300548, -7.995220 | 18 |
| B19 | 31.247844, -7.985308 | 31.247870, -7.985336 | 4 |
| B20 | 31.181004, -7.941928 | 31.181296, -7.942058 | 35 |
| B21 | 31.142836, -7.901583 | 31.142822, -7.901662 | 8 |
| B24 | 30.977030, -7.920750 | 30.976993, -7.920767 | 4 |
| B25 | 30.924160, -7.947380 | 30.924173, -7.947415 | 4 |
| B26 | 30.891140, -7.927450 | 30.891150, -7.927481 | 3 |
| B27 | 30.837850, -7.902030 | 30.837877, -7.902012 | 3 |
| B28 | 30.791710, -7.917570 | 30.791667, -7.917573 | 5 |
| B29 | 30.741280, -7.933020 | 30.741431, -7.933101 | 18 |

Outliers (> 300 m): **A04** (6.6 km, longitude 9,79 for 9,72; re-read confirmed the sheet says 9,79), **A09** (5.4 km, coordinates copied from A8; re-read confirmed) and **A05** (48.6 km, but here the header is wrong, see above). B19 was listed here as a 33 km outlier. The re-read shows the first decimal of its latitude is this writer's looped 2, so the sheet reads 31.247844, 4 m from the logger. The re-readers also offered other readings for A12, B21 and B24; checked on the photos, the transcriptions stand (see Discrepancies). Two sites fall between 100 and 300 m: A06 (200 m; the 4th latitude decimal on IMG_1171_2 is overwritten, reading 31.28689 against 31.28869) and B17 (170 m, longitude -7.94750 against -7.94572, the same on all three photos). Sites with no sheet position: B07 (latitude and longitude scribbled out, only 31.83 / 7.95 legible, consistent with the header) and B04 (latitude digits overwritten; the longitude -7.961288 is 2 m from the header, and the reading 31.963829 fits it). The Remote form has no position. A22 and B12 have only the sheet position.

## Loggers and coils

Times are local (UTC+1). The interval is the header start to the end of recording (the 2025 or 2023 table FinishTime, else the survey.yaml end). A05 uses the sheet, because its header is A14. A22 uses the 2023 table and B12 has a deployment time only. "Rx (sheet)" is the unit number read from the Rx box.

| site | from | to | Rx (sheet) | serial (header) | Bx | By |
|---|---|---|---|---|---|---|
| B01 | 2023-02-14 15:29 | 2023-02-18 11:09 | Lemi 5 | 5 | 115 | 116 |
| B02 | 2023-02-15 12:40 | 2023-02-18 12:25 | Lemi 423 N008 | 8 | 241 | 243 |
| A25 | 2023-02-21 16:53 | 2023-02-22 10:05 | Lemi N°8 | 8 | 115 | 116 |
| A26 | 2023-02-23 12:36 | 2023-02-26 11:12 | Lemi N°8 | 8 | 115 | 116 |
| A27 | 2023-02-23 14:26 | 2023-02-23 18:56 | Lemi 5 | 5 | 129 | 131 |
| A24 | 2023-02-24 13:26 | 2023-02-27 09:13 | Lemi: 3 | 3 | 241 | 243 |
| A23 | 2023-02-24 16:37 | 2023-02-26 06:07 | Lemi: 6 | 6 | 123 | 124 |
| A22 | 2023-02-26 14:47 | 2023-03-01 11:31 | LEMI:08 | 8 | 115 | 116 |
| A21 | 2023-02-27 12:35 | 2023-03-02 09:33 | Lemi 03 | 3 | 129 | 131 |
| A20 | 2023-02-27 13:59 | 2023-03-02 10:15 | Lemi 5 | 5 | 123 | 124 |
| A19 | 2023-02-27 16:48 | 2023-03-02 10:51 | Lemi 6 | 6 | 241 | 243 |
| A31 | 2023-03-01 18:09 | 2023-03-05 09:55 | Lemi N°8 | 8 | 115 | 116 |
| A18 | 2023-03-02 13:38 | 2023-03-06 13:32 | Lemi 5 | 5 | 123 | 124 |
| A17 | 2023-03-02 15:05 | 2023-03-06 03:06 | Lemi N°3 | 3 | 129 | 131 |
| A16 | 2023-03-02 17:32 | 2023-03-06 12:02 | Lemi N° 6 | 6 | 241 | 243 |
| A30 | 2023-03-05 12:14 | 2023-03-09 10:08 | Lemi N°8 | 8 | 115 | 116 |
| A29 | 2023-03-07 11:17 | 2023-03-10 09:20 | Lemi N°6 | 6 | 129 | 131 |
| A28 | 2023-03-07 12:32 | 2023-03-10 09:49 | Lemi N°5 | 5 | 123 | 124 |
| B29 | 2023-03-12 12:08 | 2023-03-14 09:52 | Lemi N°3 | 3 | 123 | 124 |
| B28 | 2023-03-12 13:30 | 2023-03-14 10:30 | 6 | 6 | 115 | 116 |
| B27 | 2023-03-12 15:33 | 2023-03-14 11:09 | Lemi: 8 | 8 | 129 | 131 |
| B26 | 2023-03-14 12:52 | 2023-03-16 12:35 | Lemi N° 6 | 6 | 129 | 131 |
| B25 | 2023-03-14 14:55 | 2023-03-16 13:30 | Lemi: 3 | 3 | 115 | 116 |
| B24 | 2023-03-14 18:40 | 2023-03-16 15:06 | Lemi N°8 | 8 | 121 | 124 |
| A01 | 2023-07-11 10:05 | 2023-07-13 07:52 | Lemi 423 No: 014 | 14 | 119 | 121 |
| A02 | 2023-07-11 13:42 | 2023-07-13 08:46 | Lemi 423 N° 011 | 11 | 112 | 114 |
| A06 | 2023-07-11 15:43 | 2023-07-13 12:33 | Lemi 423 N°13 | 13 | 240 | 242 |
| A04 | 2023-07-12 11:02 | 2023-07-14 08:56 | Lemi423 N°12 | 12 | 117 | 118 |
| A08 | 2023-07-12 13:07 | 2023-07-14 09:37 | Lemi 423 N°07 | 7 | 134 | 136 |
| A07 | 2023-07-12 13:32 | 2023-07-14 09:42 | 423 N°0-4 | 4 | 125 | 126 |
| A09 | 2023-07-12 15:43 | 2023-07-14 10:44 | Lemi 423 N°33 | 33 | 137 | 138 |
| A05 | 2023-07-13 or 14 11:35 | 10:30, day not written | Lemi 423 No: 11 | 12 | 112 | 114 |
| A10 | 2023-07-13 12:25 | 2023-07-15 13:01 | Lemi 423 N°14 | 14 | 127 | 128 |
| A03 | 2023-07-13 14:29 | 2023-07-15 11:04 | Lemi 423 No: 13 | 13 | 240 | 242 |
| A11 | 2023-07-13 15:02 | 2023-07-15 11:30 | Lemi423 N°9 | 9 | 119 | 121 |
| A12 | 2023-07-14 12:23 | 2023-07-16 13:00 | Lemi 423 N°4 | 4 | 125 | 126 |
| A15 | 2023-07-14 14:18 | 2023-07-16 09:07 | LEmi 423 N.?33 | 33 | 137 | 138 |
| A14 | 2023-07-14 16:23 | 2023-07-16 13:50 | Lemi 423 N°12 | 12 | 117 | 118 |
| A13 | 2023-07-14 17:57 | 2023-07-16 10:03 | Lemi 423 N007 | 7 | 134 | 136 |
| B05 | 2023-07-17 16:11 | 2023-07-20 10:37 | Lemi 423 N°13 | 13 | 241 | 243 |
| B06 | 2023-07-18 12:20 | 2023-07-23 11:10 | Lemi 423 N°?3 | 33 | 240 | 242 |
| B07 | 2023-07-18 14:21 | 2023-07-20 11:16 | Lemi423 N°09 | 9 | 119 | 121 |
| B03 | 2023-07-19 11:22 | 2023-07-23 10:02 | Lemi 423 N°: 5 | 5 | 134 | 136 |
| B04 | 2023-07-19 13:21 | 2023-07-23 10:35 | Lemi423 N°14 | 14 | 117 | 118 |
| B08 | 2023-07-20 13:04 | 2023-07-24 10:38 | Lemi 423 N° | 13 | 119 | 121 |
| B09 | 2023-07-20 14:33 | 2023-07-24 10:59 | Lemi 422 | 9 | 137 | 138 |
| B10 | 2023-07-20 16:20 | 2023-07-25 18:05 | Lemi 423 N°4 | 4 | 241 | 243 |
| B12 | 2023-07-22 11:44 | 2023-07-22 12:00 | Lemi 423 N°7 |  | 125 | 126 |
| B14 | 2023-07-22 14:16 | 2023-07-25 10:31 | Lemi 423 N°11 | 11 | 127 | 128 |
| B15 | 2023-07-22 17:03 | 2023-07-25 09:19 | Lemi 423 N°12 | 12 | 112 | 114 |
| B16 | 2023-07-23 14:33 | 2023-07-26 12:12 | Lemi 423 N°33 | 33 | 240 | 242 |
| B17 | 2023-07-23 15:51 | 2023-07-26 11:44 | Lemi 423 N°14 | 14 | 117 | 118 |
| B18 | 2023-07-23 17:47 | 2023-07-26 10:56 | Lemi 423 N° 5 | 5 | 134 | 136 |
| B11 | 2023-07-24 13:08 | 2023-07-28 11:45 | Lemi 423 N° 9 | 9 | 137 | 138 |
| B13 | 2023-07-24 16:27 | 2023-07-27 13:20 | Lemi 423 N°13 | 13 | 119 | 121 |
| B19 | 2023-07-25 13:30 | 2023-07-27 12:15 | Lemi 423 N°7 | 7 | 127 | 128 |
| B20 | 2023-07-25 14:49 | 2023-07-27 11:40 | Lemi 423 N°11 | 11 | 125 | 126 |
| B21 | 2023-07-25 16:00 | 2023-07-27 10:56 | Lemi423 N°12 | 12 | 112 | 114 |
| R05 | - | - | Lemi423 | 34 | - | - |

**Coil pairs in order of use:**

- 112/114: A02 -> A05 -> B15 -> B21
- 115/116: B01 -> A25 -> A26 -> A22 -> A31 -> A30 -> B28 -> B25
- 117/118: A04 -> A14 -> B04 -> B17
- 119/121: A01 -> A11 -> B07 -> B08 -> B13
- 121/124: B24
- 123/124: A23 -> A20 -> A18 -> A28 -> B29
- 125/126: A07 -> A12 -> B12 -> B20
- 127/128: A10 -> B14 -> B19
- 129/131: A27 -> A21 -> A17 -> A29 -> B27 -> B26
- 134/136: A08 -> A13 -> B03 -> B18
- 137/138: A09 -> A15 -> B09 -> B11
- 240/242: A06 -> A03 -> B06 -> B16
- 241/243: B02 -> A24 -> A19 -> A16 -> B05 -> B10

**No coil is at two sites at once.** Every pair moves from site to site without overlap. The sheets agree with the tables in all but three cases. A11 Bx reads 119 on the sheet (a g-shaped 9 written over another digit) against 118 in the 2025 table. B24 has 121/124, which is not a pair used anywhere else; 123/124 came off B29 that morning, so Bx is probably 123. A24's coils are shifted in the tables (see the azimuth item).

**Loggers.** The sheet unit number matches the header serial at every site where one is legible, with these exceptions. B16 was transcribed as 32 on three photos. The re-read of IMG_0926_2 gives 33 (confidence about 0.7): the second 3 has a flat top, and its lower bowl sits below the Rx box line, which made it look like a 2. That matches serial 33. B06 reads ?3 and A15 reads ?33, both consistent with 33. B08 and B09 give no unit number. A05's 11 is the real A5 logger. In the headers, no logger is at two sites at once except the known copies (A05 = A14, B30 = B28, B31 = B29) and C21, whose header is identical to C07 (C21new looks like the real C21).

## B30/B31 and B12/B22/B23

**B30 and B31.** For the March line-B forms, the students wrote their own numbers on the Site line: AM_B26 (Targa), AM-B27 (Tagadirt), AM_B28 (Tifkilt), AM-B29 (Iguidy), AM-B30 (Tighariwine) and BH-B31 (Iguidi). Someone later added corner codes two lower (B25-B29). There is none on the Targa page. The corner codes are the survey numbers: each form sits within 20 m of that survey header, with the same logger, and a deployment time within 20 minutes of the logger start. The 2025 table and the 2023-10 table (B-29, B-30, B-31) still use the Site-line numbers. That is how survey.yaml ended up with B30/B31 folders that duplicate B28/B29. The evidence on the sheets is as follows:
- "AM-B30" appears only on the Tighariwine form: 4 photos (IMG_0129_2, IMG_0759_2, IMG_1328_2, IMG_1472_2), all deployed 12-03-2023 13:30, 30.79171 N 7.91757 W, logger 6, coils 115/116, picked up 14/03 10:40. That is survey B28 exactly.
- "BH-B31" / "AM_B31" appears only on the Iguidi form: 4 photos, all 12-03-2023 11:49, 30.74128 N 7.93302 W, logger 3, coils 123/124, picked up 14/03 10:00. That is survey B29 exactly.
- No sheet with a different date, position or logger names B30 or B31. **So there is no evidence of any deployment beyond B28/B29.** The B30/B31 entries in survey.yaml can be dropped.
- One consequence: the 2025 table's "B28" row sits at Tifkilt (survey B26) but carries 52.8/53.5. 52.8 is the Tighariwine Ex (50 + 2.8). 53.5 is the Tighariwine Ey with the Ey/E cell taken as 50. The cell is a clear 30 (re-read on IMG_1472_2), so Ey = 33.5 m. The 2025 "B30" row, which is Tighariwine, carries 50/50. survey.yaml B28 took 52.8/53.5 by name, which suits Tighariwine on Ex but not on Ey.

**B12.** There is a sheet: Dar Soulaimani (IMG_1201_2 lower), 22-07-2023 11:44, 31.560112 N 8.009214 W, logger 7, coils 125/126, arms 5/45/35/3. Its notes say "A refaire !! To be done again", and IMG_1873_2 lower is a blurred second photo of the same form. Logger 7 next appears at B19 on 25 July. The site was set out, judged bad and never redone, so no B12 data exist. The re-read confirmed the sheet. That it was never redone rests only on the absence of a B12 recording.
**B22 and B23.** No sheet in any photo or the PDF. Nothing on paper suggests they were ever deployed. Most likely the numbers were simply skipped between B21 (Imlile, 25 July) and the renumbered March sites.

## Discrepancies

Severity is high for a dipole, position, logger or site-identity disagreement and low otherwise. Each of the 42 high-severity entries was re-read against its photo by a reader who tried to prove the transcription wrong. The low-severity entries were not re-read, though several of their values were read in passing.

### Confirmed disagreements (genuine)

These transcriptions stood. Each is a real disagreement between a sheet and survey.yaml or a table, for Ben to settle.

**Dipole lengths (29).** Cells are Ex/N, Ex/S or Ey/E, Ey/W as re-read. The rho factor is (current / sheet)^2 with the arms added. The last column gives the re-reader's caveat.

| id | site | comp | cells as re-read | sheet (m) | other (source) | rho factor | note |
|---|---|---|---|---|---|---|---|
| FN001 | A01 | Ex, Ey | 50 / 50, 5 / 4 (both photos) | 100 / 9, impossible | 55 / 54 (survey.yaml, 2025) | - | Mud map: N and E short, S and W long. 55/54 fits the cells written under the wrong headings: a repair, not a reading. Notes: "Electric swapped in the box". |
| FN002 | A02 | Ex | 2 / 50, a darker 4 over the 5 | 42 or 52 | 42 (survey.yaml, 2025) | 1.00 or x0.65 | The 4 is a later correction in another pen, so 42 is more likely, as in survey.yaml. |
| FN009 | B01 | Ex | 4 / 50 | 54 | 50 (survey.yaml, 2025) | x0.86 | Mud map has short N and E arms. B02 on the same page uses the same layout. |
| FN010 | B01 | Ey | 4 / 50 | 54 | 50 (survey.yaml, 2025) | x0.86 | 54 m assumes the two arms are in line. |
| FN011 | B02 | Ex | 4,9 / 50 | 54.9 | 50 (survey.yaml, 2025) | x0.83 | Reader doubts the sum: this mud map is a symmetric cross. |
| FN012 | B02 | Ey | 4 / 50 | 54 | 50 (survey.yaml, 2025) | x0.86 | Same doubt as FN011. |
| FN013 | B07 | Ey | 5 / 38 | 43 | 50 (survey.yaml, 2025) | x1.35 | Reader doubts the sum and would keep 50. 50 fits only if the 5 is a shortened 50 and the 38 is ignored. |
| FN014 | B10 | Ex | 50 / 3 | 53 | 50 (survey.yaml, 2025) | x0.89 | Mud map: long N arm, short S stub. |
| FN015 | B10 | Ey | 3 / 50 | 53 | 50 (survey.yaml, 2025) | x0.89 | The map has the short arm on the W, the grid on the E. The total is the same. |
| FN017 | B13 | Ex | 50 / 3 | 53 | 50 (survey.yaml, 2025) | x0.89 | Mud map: S and W electrodes close to the box. |
| FN018 | B13 | Ey | 50 / 5 | 55 | 50 (survey.yaml, 2025) | x0.83 | As FN017. |
| FN019 | B14 | Ex | 50 / 3 | 53 | 50 (survey.yaml, 2025) | x0.89 | Mud map: long N and W, short S and E. |
| FN020 | B14 | Ey | 3 / 50 | 53 | 50 (survey.yaml, 2025) | x0.89 | B15 on the same page uses the same layout. |
| FN021 | B15 | Ex | 50 / 4 | 54 | 50 (survey.yaml, 2025) | x0.86 | Mud map: long N and E, short S and W. |
| FN022 | B15 | Ey | 50 / 3 | 53 | 50 (survey.yaml, 2025) | x0.89 | As FN021. |
| FN024 | B19 | Ex | 35 / 4 | 39 | 50 (survey.yaml, 2025) | x1.64 | Very uneven arms beside a power line and a transmission line. Confirm the 4 m arms were real. |
| FN025 | B19 | Ey | 4 / 25 | 29 | 50 (survey.yaml, 2025) | x2.97 | No 50 anywhere on the B19 sheet. |
| FN027 | B20 | Ex | 21 / 2 | 23 | 50 (survey.yaml, 2025) | x4.73 | Reader doubts the 2 m arms: the mud map runs both lines well out on each side. |
| FN028 | B21 | Ex | 27 / 2 | 29 | 50 (survey.yaml, 2025) | x2.97 | The 27 is clear, with this writer's crossed 7. |
| FN029 | B21 | Ey | 25 / 2 | 27 | 50 (survey.yaml, 2025) | x3.43 | Mud map: one far and one near electrode on each line. |
| FN030 | B24 | Ex | 2 / 33 | 35 | 50 (2025 row B26; survey.yaml empty) | x2.04 | Re-readers compared with 2025 row B26, which is Targa, so survey B24. |
| FN031 | B24 | Ey | 34 / 2 | 36 | 50 (2025 row B26; survey.yaml empty) | x1.93 | River and village terraces may have forced the layout. |
| FN033 | B25 | Ex | 32 / 0.5 | 32.5 | 50 (2025 row B27; survey.yaml empty) | x2.37 | Mud map: long N and W, short S and E. |
| FN034 | B25 | Ey | 2 / 16 | 18 | 50 (2025 row B27; survey.yaml empty) | x7.72 | Notes say the E cables were badly connected in the box, found after pickup. The E channels may be bad whatever the length. |
| FN037 | B27 | Ey | 50 / 3 | 53 | 50 (survey.yaml, 2025 row B29) | x0.89 | Ex on the same sheet is 47 / 1 = 48. |
| FN038 | B28 | Ex | 50 / 2.8 | 52.8 | 50 (2025 row B30) | x0.90 | Agrees with survey.yaml's 52.8. The 2.8 has a mid-height decimal point. |
| FN039 | B28 | Ey | 30 / 3.5 | 33.5 | 53.5 (survey.yaml) | x2.55 | The 3 in 30 matches this writer's other 3s, not the flat-topped 5 in the Ex/N 50. |
| FN040 | B28 | Ey | 30 / 3.5 | 33.5 | 50 (2025 row B30) | x2.23 | Reader suggests Ey may be 30 (x2.78 against 50). |
| FN041 | B29 | Ex | 50 / 4 | 54 | 50 (survey.yaml, 2025 row B31) | x0.86 | Mud map draws the logger off centre (long N, short S), but the reader calls 54 unproven. |

**Positions, site identity, azimuth and the remote date (8).**

| id | site | field | sheet as re-read | other (source) | what it means |
|---|---|---|---|---|---|
| FN003 | A04 | position | longitude 9,79267509 as written, no sign | -9.722686 (B423 header) | A slip on the sheet, 6.6 km off; the other digits fit the logger if the second decimal 9 was meant as a 2. The header position stands. Nothing to change. |
| FN005 | A09 | position | 31,20090471 / 9.69815563, digit for digit the A8 form | 31.167268, -9.657706 (B423 header) | Copied from A8, which was filled in 2 h 45 min earlier; the A8 cable note is repeated too. The header position stands. Nothing to change. |
| FN004 | A05 | site identity | A-5 at 31.340706, -9.713373, logger 11, coils 112/114, 11:35 on 13 July overwritten to 14 ('14/07/2013' added above) | header 30.917771, -9.586553, serial 12 = A14 (B423 header, A05/A14 folders) | A5's recording is not in the archive, and the A05 folder is A14. Find logger 11's July files or drop A05. Not checked from the photo: that the folders are identical. |
| FN007 | A22 | site identity | AM-A22 at 30.55512, -9.56010, LEMI:08, 26/02/2023, coils 115/116, arms 46 / 3, 50 / 2.5, SD card 10 | no A22 in survey.yaml or the archive; 2023 tables list it (26 Feb-1 Mar) | A22 was deployed. The gap is on the data side. Contact resistances of 3-6 kOhm were logged as high because of rocky ground. |
| FN016 | B12 | site identity | Dar Soulaimani, B12, 22-07-2023 11:44, logger 7, coils 125/126, "A refaire !! To be done again" | no B12 data | Set out and abandoned. "Never redone" rests only on there being no B12 recording. |
| FN032 | B24 | site identity | Site line AM_B26, Targa, 14-03-2023 18:41, Lemi N° 8; no corner code visible (a loose sheet covers that corner) | survey B24 (4 m, serial 8, start 18:40) | The form is survey B24. Some re-readers took the "B24" label for an error because they compared against 2025 row B26, which uses the students' numbering. |
| FN008 | A24 | azimuth_ey | no azimuth anywhere; Bx 241, By 243; the mud map cross implies Ey 90 | azimuth_ey 241, BxCoil 243, ByCoil - (survey.yaml, 2025, 2023 table) | The coil serials slid one column left in the tables. survey.yaml azimuth_ey 241 should be 90. Notes also say "Electric cables swopped in the box". The Ex arms were corrected on the sheet (a 48 struck from Ex/N and written into Ex/S), but the 51.5 m total is unaffected. |
| FN042 | R05 | site identity (date) | "Remote", Geolab, 06/07/2023, no time, coordinates, coils or sample rate; SD card 57 | R05 header starts 2023-07-19 08:33 UTC | The day is clearly 06, and a month-first reading (7 June) is earlier still. The sheet cannot explain the 13-day gap or the 1 Hz setting; only the logger files can. |

### Corrected transcriptions

| id | site | field | transcribed | re-read | outcome |
|---|---|---|---|---|---|
| FN006 | A12 | Ex/N, Ey/W | Ex/N 60; Ey/W ? | Ex/N 50: the first digit is this writer's 5, like the 5 in Bx 125, and unlike the compact 6s in 126 and 12,76. Ey/W is a 3 and a 4 overlaid. Ex/S is a 3 with an extra stroke. | Resolved for Ex: 50 + 3 = 53 m, as in survey.yaml. Ey is 53 or 54 m (within 2 %), so survey.yaml's 54 can stay. |
| FN023 | B16 | logger | Lemi 423 N°32 | N°33. The second 3 is flat-topped, and its lower bowl sits below the Rx box line. Confidence about 0.7; it may be a 2 corrected to 3. | Resolved: matches header serial 33. Only IMG_0926_2 was re-read. |
| FN026 | B19 | latitude | 31.547844 | 31.247844. The first decimal is this writer's looped 2, as in the date; the writer's 5s have a straight top bar. | Resolved: the sheet is 4 m from the logger and no longer an outlier. |
| FN035 | B26 | 2025 table row B28 | The claim cited IMG_1472_2 for the Tifkilt cells and called 52.8/53.5 the Tighariwine arms. | IMG_1472_2 holds Tighariwine (B28) and Iguidi (B29), not Tifkilt. Tighariwine gives Ex 50 + 2.8 = 52.8 and Ey 30 + 3.5 = 33.5. | Claim corrected. The 2025 row B28 (at Tifkilt) carries Tighariwine's Ex and a Tighariwine Ey built with Ey/E read as 50. The mix-up in the table is real, and its effect on survey.yaml is FN039. Tifkilt's own cells (50 / blank, 50 / 3) were confirmed under FN036. |
| FN036 | B26 | Ey | 50 + 3 = 53 | Same digits: Ey/E 50, Ey/W 3, Ex/S blank. The reader rejects the sum and would keep 50 m. | The digits stand. The dispute is whether the arms add, which stays open (see Do the arms add?). The site table keeps 53, like every other site. |

### Low severity, not re-read

| id | site | field | sheet | other (source) | status |
|---|---|---|---|---|---|
| FN043 | A01 | deploy date | 2023-07-12 | 2023-07-11 10:05 (header start, local) | Read in passing (FN001): the day's second digit is overwritten, 11 or 12. No conflict. |
| FN044 | A02 | deploy date | 2023-07-12 | 2023-07-11 13:42 (header start, local) | Read in passing (FN002): a 1 and a 2 overwritten. No conflict. |
| FN045 | A02 | r_ng_kohm | 233 (IMG_0820_2 lower) | 933 (IMG_2037_2 lower) | The FN002 reader also read 233 on IMG_0820_2. IMG_2037_2 not re-read. Open. |
| FN046 | A06 | sd_card | 55 (IMG_1171_2) | 65 (IMG_1730_2) | Open. |
| FN047 | A11 | bx_coil | 119 | 118 (2025 row A11) | Open. |
| FN048 | A13 | site code | AA3 | A13 (IMG_0951_2 lower) | Position (3 m) and logger 7 settle it: A13. |
| FN049 | A13 | v_ew_mv | 8,2 | 9,2 (IMG_0951_2 lower) | Open; QC value only. |
| FN050 | A15 | site code | AA5 / A1? | A15 (B423 header) | Position (5 m) and logger 33 settle it: A15. |
| FN051 | A23 | Ex | 46 + ?,5 (pdf p8) | 50.5 (survey.yaml, 2023 tables) | Open; survey.yaml assumes 4,5. |
| FN052 | A23 | pickup | 2023-02-27 10:08 | recording ended 2023-02-26 06:07 (2025 FinishTime) | Open: the logger stopped 28 h before pickup. |
| FN053 | B08 | logger | no unit number | 13 (header) | Nothing to compare. |
| FN054 | B09 | logger | "Lemi 422" | 9 (header) | Nothing to compare. |
| FN055 | B19 | sd_card | 65 (IMG_0115_2) | 55 (IMG_0604_2) | Re-readers split: two read 65 and one 55. The digit is a 6 and a 5 overlaid. Open. |
| FN056 | B24 | bx_coil | 121 (By 124) | 123/124 (coil chain) | Read in passing (FN030, FN031): the sheet does say 121. 123 remains an inference from the coil chain. |
| FN057 | B25 | site name | Site line AM-B27 | corner code B25 | Read in passing (FN033, FN034): the labels are as transcribed. Survey number = Site-line number - 2. |
| FN058 | B26 | Ex | 50 + blank | 50 (survey.yaml); 52.8 (2025 row B28) | Read in passing (FN036): Ex/S is blank. Open. |
| FN059 | B26 | site name | Site line AM_B28 | corner code B-26 | Read in passing (FN036): as transcribed. |
| FN060 | B27 | site name | Site line AM-B29 | corner code B27 | Read in passing (FN037): as transcribed. |
| FN061 | B27 | v_ng_mv | 25. (IMG_0596_2) | 85. (IMG_0707_2) | Open; QC value only. |
| FN062 | B28 | site name | Site line AM-B30 | corner code B28 | Read in passing (FN038-FN040): as transcribed. |
| FN063 | B29 | site name | Site line BH-B31 / AM_B31 | corner code B29 | Read in passing (FN041): as transcribed. |
| FN064 | R05 | Ex, Ey | 2 / 3, 50 / 50 | 50 / 50 (survey.yaml) | Read in passing (FN042): as transcribed. R05 is excluded, so this matters only if the site is reused. |
| FN065 | R05 | logger | "Lemi423" | 34 (header) | Read in passing (FN042): no unit number. |

### Other readings the re-readers gave in passing

The re-readers transcribed whole half-sheets, and a few values they were not asked about came out different. Three of these would have moved a position or a date, and I checked those on the photos:

- **B21 position and date.** Both B21 re-readers read 31.14983604, -7.90118324 and 21.07.2023. That would put the sheet 780 m from the logger and four days early. On IMG_1323_2, this writer's 2 has a closed loop (as in "2023") and the 5 is a flag shaped like "ſ" (as in the "25" of the date). The sheet reads 31.14283604, -7.90158324 and 25.07.2023, as transcribed. That is 8 m from the logger, and 25 July fits the logger start and coils 112/114 coming off B15 that morning.
- **A12 longitude.** Re-read as -9,976395. The crop shows -9,5763?5, with the fifth decimal overwritten. The transcription stands, 86 m from the logger.
- **B24 longitude.** Two re-readers gave -7.920075. The crop shows -7.92075, as transcribed, 4 m from the logger.

Not checked, QC values or names only: A02 N-S 18.3 kOhm and 8.8 mV (transcribed 12.3 and 8.2), B16 battery 12.71 V (12.75), B19 N-G 21.8 or 31.8 mV, A22 elevation 214 or 211 m, A04 area Boutazante (transcribed Bontazonte).

## Other observations

- The 2025 table and the 2023 tables drop the leading digit of elevations of 1000 m and above (A19 168.9 for 1168.9, B18 245 for 1245, B29 row 218.7 for 1218.7, the line-C and line-D rows). Use the header elevations, as the site table does.
- The survey.yaml `end` is the end of the last 90-minute file, so it runs up to 90 minutes past the true stop. The pickup checks use the table FinishTime instead. Every pickup on the sheets fits it within an hour, except A23.
- The second day digit of the A01 and A02 dates is overwritten (1 and 2), so 11 or 12 July; the loggers started on 11 July.

## What to check by hand, ranked

1. **A24 azimuth_ey: 241 in survey.yaml should be 90.** The 241 is the Bx coil serial, slid into the azimuth column. It is one number with no ambiguity. Left as it is, it rotates Ey by 151 degrees wherever the azimuths are used. The sheet also says "Electric cables swopped in the box", so include A24 in item 5.
2. **B28 Ey: 53.5 m in survey.yaml should be 33.5 m** (30 m if the arms do not add). The Ey/E cell was transcribed as 30 on all four photos and re-read as a clear 30 on IMG_1472_2. rho_yx x2.55 (x3.18).
3. **B19, B20 Ex, B21, B24, B25 and B07 Ey.** survey.yaml has 50/50 or nothing, and the sheets give 16-43 m. These are wrong under either reading of the cells (see Do the arms add?), with rho factors of 1.4 to 10. Decide on the lengths and fill survey.yaml. B25's notes say the E cables were badly connected in the box, so its E channels may be unusable anyway.
4. **Whether the arms add.** Ask whoever ran the crews, or check the kit's cable lengths: was the logger beside one electrode, with a long cable to the other? If yes, B01, B02, B07 Ex, B10, B13-B15, B20 Ey, B26 Ey, B27 Ey and B29 Ex go from 50 to 52-55 m (rho x0.83-0.92). If no, the arm sums survey.yaml already uses on line A and B03-B18 are 4-10 % too long. Either way the effect is small next to static shift. Decide once for the whole survey.
5. **"Electric (cables) swopped in the box"** is on the sheets for A01, A04, A08, A09, A11, A17, A18, A19, A20, A24, A25, A31, B01, B02 and B07. survey.yaml mentions it only for A17-A20, A24, A25 and A31. The note does not say whether Ex and Ey were exchanged or a dipole was reversed, and the fix differs: azimuth_ex/ey 90/0 for an exchange, 180 or 270 for a reversal. Check the phase quadrants of these sites against their neighbours before trusting 0/90. The site table keeps 0/90.
6. **A05.** Search the raw downloads for logger 11 from 13/14 to 16 July 2023. The A05 folder is a copy of A14, so either reprocess A05 from the right files or drop it.
7. **A22.** Search the downloads for logger 8 from 26 Feb to 1 Mar 2023. The tables list it but the archive does not have it.
8. **Photo readings still open (low impact):** whether to keep survey.yaml's A01 repair (55/54), A02 Ex/S (40 likely, so Ex 42 m), A12 Ey/W (3 or 4), A23 Ex/S (blotted, pdf p8), B26 Ex/S (blank) and the B16 logger (33 at about 0.7; IMG_1500_2 and IMG_1866_2 not re-read).
9. **R05 / Remote form.** The form is dated 06/07/2023 but R05 starts on 19 July. Was there an earlier July remote recording that is missing? This matters only if the July remote is ever needed, since R05 is excluded (1 Hz).
10. **Field problems that need masks, not metadata:** B05 (south electric cable cut), B29 (northern cable possibly broken after pickup), B25 (electric cables badly connected in the box, found after pickup), A26 (electrode pulled up and chewed after about 48 h), A23 (recording stopped 28 h before pickup) and B04 (a note, mostly illegible, about the signal varying).
11. **Low-legibility records:** IMG_1873_2 (both halves, out of focus), IMG_0266_2 lower (curled) and IMG_1476_2 upper (cropped) were matched only through the values they share with clearer photos.
