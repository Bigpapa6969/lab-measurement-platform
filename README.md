# Lab Measurement Platform

A full-stack engineering tool for capturing, analysing, and reporting on electronic waveform data. Upload a real oscilloscope CSV or generate a synthetic signal — then get instant frequency, RMS, duty cycle, and rise-time measurements, interactive plots, pass/fail limit checking, and a downloadable PDF test report.

Built as a portfolio project demonstrating professional software architecture across a Python/FastAPI backend and a React/TypeScript frontend.

---

## What it does

| Feature | Detail |
|---|---|
| **Mock waveform generator** | Sine, square, PWM, triangle, DC — configurable frequency, amplitude, noise, duty cycle |
| **CSV ingestion** | Auto-detects Rigol, Tektronix, LTspice, and generic formats |
| **Signal analysis** | RMS, frequency, FFT, duty cycle, rise/fall time — all computed in NumPy/SciPy |
| **Pass/Fail limits** | User-defined min/max bounds on any metric; aggregate PASS/FAIL verdict |
| **Interactive plots** | WebGL-accelerated time-domain and FFT plots via Plotly.js |
| **PDF report generator** | Multi-page A4 PDF with matplotlib plots and ReportLab tables |

---

## Tech stack

**Backend** — Python 3.11 · FastAPI · Pydantic v2 · NumPy · SciPy · matplotlib · ReportLab

**Frontend** — React 18 · TypeScript · Vite · Plotly.js · Tailwind CSS

**Tests** — 116 pytest tests covering unit math, ingestion, and full HTTP round-trips

---

## Running the project

**One-time setup**

```bash
# Backend
cd backend
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
cd ..
```

**Start both servers with one command**

```bash
python start.py
```

Open **http://localhost:5173** in your browser. The frontend proxies all API requests to the FastAPI backend on port 8000 — no CORS configuration needed.

**API docs (Swagger UI):** http://localhost:8000/docs

**Run the tests:**

```bash
cd backend
python -m pytest -v
```

---

## Project structure

```
lab-measurement-platform/
├── start.py                            # Single-command launcher (backend + frontend)
├── backend/
│   ├── app/
│   │   ├── services/
│   │   │   ├── analysis_engine.py      # Pure NumPy/SciPy signal math
│   │   │   ├── report_generator.py     # matplotlib + ReportLab PDF builder
│   │   │   └── ingestion/
│   │   │       ├── mock_oscilloscope.py
│   │   │       └── csv_parser.py
│   │   ├── api/routes/                 # measurements · analysis · reports
│   │   ├── models/                     # Pydantic request/response schemas
│   │   └── core/                       # config · exceptions
│   └── tests/                          # 116 tests total
└── frontend/
    └── src/
        ├── components/                 # Dashboard · AnalysisSidebar · ReportModal · Plots
        ├── hooks/                      # useWaveform · useAnalysis
        └── services/api.ts             # Typed fetch client
```

---

## The signal analysis — how the math works

All analysis lives in `backend/app/services/analysis_engine.py`. Here is the reasoning behind each algorithm.

---

### RMS voltage

**True RMS** is the "heating equivalent" voltage — a 1 V RMS signal delivers the same power to a resistor as 1 V DC, regardless of the waveform shape.

$$V_{rms} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} v_i^2}$$

**AC RMS** removes the DC offset by subtracting the mean before squaring. This is mathematically identical to the standard deviation:

$$V_{rms,ac} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} (v_i - \bar{v})^2}$$

**Average power** into a resistive load:

$$P = \frac{V_{rms}^2}{R}$$

The RMS definition exists precisely so this formula works for any waveform shape, not just DC.

---

### Frequency — zero-crossing method

Frequency is estimated by measuring the time between consecutive positive-going crossings of the signal mean — one crossing per cycle, so the spacing between crossings equals one period.

**Why the mean?** It is a robust centre-line that works for sine, square, and PWM without needing to know the signal type in advance.

**Sub-sample interpolation** gives crossing times finer than one sample interval. Between sample $i$ (below threshold) and sample $i+1$ (above threshold):

$$t_{cross} = t_i + \frac{V_{threshold} - v_i}{v_{i+1} - v_i} \cdot (t_{i+1} - t_i)$$

**IQR outlier rejection** removes glitch-corrupted periods before averaging. Any period more than $1.5 \times IQR$ outside the quartiles is discarded (Tukey's fence — the same rule used in box-and-whisker plots):

$$\text{valid if } \quad Q_{25} - 1.5 \cdot IQR \leq T_k \leq Q_{75} + 1.5 \cdot IQR$$

Finally: $f = 1 / \bar{T}$ where $\bar{T}$ is the mean of the surviving period estimates.

---

### FFT spectrum

**The problem — spectral leakage.** The FFT assumes the captured window repeats perfectly end-to-end. When the signal frequency does not divide evenly into the capture length, the hard boundary smears energy across many bins. A **Hann window** fixes this by tapering the signal to zero at both ends before transforming:

$$w_i = 0.5 \left(1 - \cos\!\left(\frac{2\pi i}{N-1}\right)\right)$$

**Amplitude correction.** Multiplying by the window reduces total signal energy. To recover true amplitudes, the output is scaled by the sum of window coefficients (not $N$):

$$|X_k| = \frac{2}{\displaystyle\sum_i w_i} \left| \operatorname{FFT}(v \cdot w)_k \right|$$

The factor of 2 compensates for discarding the negative-frequency half of the spectrum. The DC bin ($k = 0$) has no mirror image, so it is halved back after scaling.

**Dominant frequency** is found by taking the highest-magnitude bin while skipping DC ($k = 0$), so a large DC offset does not mask the signal's fundamental.

---

### Duty cycle

Duty cycle is the fraction of time the signal spends in the HIGH state:

$$D = \frac{N_{above}}{N_{total}} \times 100\ \%$$

The HIGH and LOW rail voltages are found from the **voltage histogram**. A square or PWM wave spends most of its time at two distinct voltages, producing a bi-modal histogram — two tall peaks separated by a valley. The algorithm locates those two peaks; their voltages become $V_{HIGH}$ and $V_{LOW}$. For sine waves and other continuous signals that are not bi-modal, the 5th and 95th percentiles are used instead.

The decision threshold is the midpoint:

$$V_{threshold} = \frac{V_{LOW} + V_{HIGH}}{2}$$

---

### Rise and fall time — 10 %/90 % convention

Rise time is measured between the 10 % and 90 % points of the voltage swing, not 0 % to 100 %. This is the IEEE standard because the very start and end of a transition are dominated by noise and parasitic effects, making 0–100 % unstable across repeated measurements.

$$V_{10} = V_{LOW} + 0.10 \times (V_{HIGH} - V_{LOW})$$
$$V_{90} = V_{LOW} + 0.90 \times (V_{HIGH} - V_{LOW})$$
$$t_{rise} = t_{90} - t_{10}$$

Each threshold crossing time uses the same sub-sample linear interpolation as the frequency method. The reported value is the **mean across all detected rising edges** in the capture window, giving a stable result even when the signal has jitter.

Fall time mirrors the same calculation in the opposite direction.

---

### Pass/Fail limit checking

Any computed metric can be given a minimum and/or maximum specification limit. The verdict per spec is:

| Condition | Result |
|---|---|
| No limits defined | NOT TESTED |
| $V_{measured} < V_{min}$ or $V_{measured} > V_{max}$ | FAIL |
| Otherwise | PASS |

The **overall verdict** is FAIL if any individual spec fails, PASS if all pass, and NOT TESTED if no specs were defined.

---

## API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/measurements/mock` | Generate a synthetic waveform |
| `POST` | `/measurements/upload` | Upload an oscilloscope CSV |
| `GET` | `/measurements/{id}` | Retrieve a stored measurement |
| `POST` | `/analysis/run` | Run the signal analysis engine |
| `GET` | `/analysis/{id}` | Retrieve a stored analysis result |
| `POST` | `/reports/generate` | Render a PDF report |
| `GET` | `/reports/{id}/download` | Download the PDF |

---

## Accepted CSV formats

| Format | Detection |
|---|---|
| **Rigol** | Header row `X,CH1,CH2,...` with unit row `Second,Volt,Volt` |
| **LTspice** | Tab-separated with a `time` column |
| **Tektronix** | Metadata lines (`Record Length`, `Sample Interval`) before data |
| **Generic** | Any two-column numeric CSV, with or without headers |

---

## License

MIT
