# DeepGIS technical report

IEEE-style technical report on DeepGIS (`IEEEtran`, journal mode): the viewer, the AI pilot,
viewport perception, the spatiotemporal world model, live vehicles and digital twins, and the
WebXR cockpit. Figures and numbers reflect the deployment as of 23 November 2026.
The agent-interface subsection (`sec:mcp`) and the two Tempe building figures were added
later the same day.

- `deepgis_techreport.tex` – source (bibliography inline, diagrams in TikZ)
- `deepgis_techreport.pdf` – built copy
- `figures/` – figures specific to the report; the others come from `docs/images/`

Build from this directory with two `pdflatex` passes. With Docker:

```bash
docker run --rm -v "$(git rev-parse --show-toplevel)":/w -w /w/manuscripts/deepgis-techreport \
  texlive/texlive:latest-small sh -c \
  'tlmgr install ieeetran preprint courier pgf booktabs cite >/dev/null;
   pdflatex deepgis_techreport.tex && pdflatex deepgis_techreport.tex'
```
