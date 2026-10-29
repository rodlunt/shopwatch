# Round 1: candidates, Australia Post, Linux

## Australia Post
- VERIFIED: MyPost Business has an "A6 for those using a DYMO or thermal printer" print setting. No supported-printer list; 4x6 not mentioned. https://auspost.com.au/business/grow-your-business/business-ideas-blog/tips-for-printing-shipping-labels
- VERIFIED: Brother AU says MyPost Business and eParcel labels are based on a 101x152mm label and names the QL-1100, QL-1110NWB, RJ4 and TD4 ranges. https://www.brother.com.au/en/contents/faq-how-to-setup-and-print-australia-post-shipping-label
- VERIFIED: international labels are A4 only, so a thermal printer will not cover them.

## Candidates seen
| Model | Price | Notes |
|---|---|---|
| Brother QL-1110NWB | $599 Officeworks (snippet $579) | up to 102mm |
| Brother QL-1100 | about $219 to $227 PB Tech, out of stock | USB only |
| Brother QL-810W / QL-800 / QL-820NWB | $218 Officeworks / $149 / about $246 | 62mm max, no 4x6 |
| Zebra ZD220 | about A$485 + GST barcodes.com.au | undated |
| Rollo / MUNBYN 4x6 | no AUD price found | Rollo Wireless US$279.99 |

## Running cost (Brother DK rolls)
- DK-11247 103x164mm, 180 labels, genuine, $64 JB Hi-Fi: about 36c each
- DK-11241 102x152mm, 200, Aimo compatible, $21.65 PB Tech: about 11c each
- DK-11221 23x23mm, 1000, $45.52 sale Oz Toner: about 4.6c each
- Generic 4x6 rolls (US figures, Castle Ink): about 2c to 4c USD each

## Linux
- VERIFIED: brother_ql (https://github.com/pklaus/brother_ql) lists QL-1100, QL-820NWB, QL-810W, QL-800 as verified and QL-1110NWB as supported but unverified; TCP, pyusb and linux_kernel backends. A container can print directly without CUPS.
- VERIFIED: the Brother CUPS driver is poor (last updated 2017, needs 32-bit libraries on some distros).
- Nothing found on Ubuntu 24.04, IPP Everywhere or raw 9100 for these models. Untested.
- Rollo and MUNBYN need a rebadged Beeprt/Rollo CUPS filter, per forum posts only.

## Gotchas
- Brother QL takes DK-type rolls only; die-cut size must match the brother_ql label definition.
- Thermal labels fade (this became the deciding factor).
- No Australia Post source confirms the QL-1110NWB specifically.
