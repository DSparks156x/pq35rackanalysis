# Steering Rack dynamic Step Response & Authority Analysis
some data on PQ35 HCA, specifically with steer datasets 237 and 311, on a 3001 8J tt rack, with the HCA torque limit patched to no longer be the limit. It EPS faults above 632 command. 

All this stuff is written by AI.... Its analysis report is fineTM, I have other comments n stuff on the notes page. Im quite frankly to lazy to write a lot of the same things it did myself so itl do. 


This repository houses the dynamic response analysis, statistical metrics, and firmware patch references for VW PQ35/PQ46 and Audi TT Mk2 steering racks under commanded steps (HCA status **HCA7**).

* **Live Interactive Dashboard**: [https://dsparks156x.github.io/pq35rackanalysis/](https://dsparks156x.github.io/pq35rackanalysis/)
* **GitHub Repository**: [https://github.com/dsparks156x/pq35rackanalysis](https://github.com/dsparks156x/pq35rackanalysis)

---

## Workspace Structure

The analysis compiles a style-consistent three-page engineering dashboard web app, fully optimized for static deployment on **GitHub Pages**:

* `index.html` (Dashboard): Hosts the dynamic performance graphs:
  * Aligned Wheel Angle Step Response.
  * Angular Velocity Profile.
  * **Angular Velocity vs. Wheel Angle Phase Portrait** (with interactive drop-down torque filters from 150 cNm to 632 cNm).
  * Statistical Aggregate Performance Table.
* `analysis.html` (Report): Rendered representation of `analysis_report.md` exploring Coulomb friction, breakaway boundaries, latency advantages, and torsion-bar torque feedback collapses.
* `notes.html` (Notes): Rendered reference documentation from `notes.md` detailing software version maps (`3001` and `3305`), disengage timebomb address patches, and command authority reject/truncate ceilings.

---

## Build and Recompile locally

If you add new data files (`.csv`) to the `data/` subdirectory, you can instantly recompile the entire multi-page site by executing:

```bash
python analyze_racks.py
```

*No external libraries are required.* The analysis engine relies entirely on Python standard library modules to parse, resample, downsample, and compile the final static website. Plotly.js and Mermaid.js are loaded via robust CDNs inside the static pages.
