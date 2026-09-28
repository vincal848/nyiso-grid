# Academic evidence on model families for day-ahead (DA) and real-time (RT) electricity price forecasting (EPF), point and probabilistic

Scope note: most of the benchmark evidence comes from European DA auctions (EPEX DE/FR/BE, Nord Pool, OMIE Spain, TGE Poland). The canonical benchmark has one US dataset (PJM, COMED zone, DA, 2013-2018). There is very little rigorous, peer-reviewed benchmark evidence for US nodal or zonal RT prices or for the congestion component of LMP. Labels used below: **[replicated]** means several independent studies or datasets found the same thing; **[single study]** means one paper; **[memory]** means a bibliographic fact I did not re-fetch in this session (the DOI is given so it can be checked).

---

## Q1. What do the major EPF reviews and benchmarks conclude?

### Takeaway
The reviews agree on four points. Use well-regularized linear expert models (LASSO-ARX, i.e. LEAR) with variance-stabilizing transforms as the benchmark to beat. Well-tuned feedforward DNNs, or NBEATSx, beat LEAR by a few percent to about 10% rMAE. Averaging forecasts across calibration windows or runs is one of the most reliable ways to gain accuracy. Probabilistic forecasting evaluated with CRPS and pinball loss has become the standard. Newer 2025-2026 reviews add deep-learning surveys and foundation-model benchmarks. None of them overturns the basic order: ensembles of domain-specific models first, with exogenous fundamentals being essential.

### Cited Findings
- **Lago, Marcjasz, De Schutter & Weron (2021), Applied Energy 293**, "Forecasting day-ahead electricity prices: A review of state-of-the-art algorithms, best practices and an open-access benchmark". The paper surveys the literature, compares LEAR and DNN across 5 markets, and releases the epftoolbox. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004); [RePEc](https://ideas.repec.org/a/eee/appene/v293y2021ics0306261921004529.html)
  - Datasets (6 years each, with the **last 2 years (104 weeks) as the test period**): NP and PJM (test 27.12.2016-24.12.2018), EPEX-FR and EPEX-BE (test 2015-2016), EPEX-DE (test 2016-2017). The PJM dataset is **COMED zonal DA prices**, with system load and COMED zonal load forecasts as exogenous inputs. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - LEAR is estimated over **4 calibration windows (56, 84, 1092, 1456 days)**. The DNN has 4 variants, one per hyperparameter/feature-selection run. "In terms of linear metrics, the four DNN models perform better than all four LEAR models for the 5 datasets". [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - Ensemble rMAE (DNN-Ens / LEAR-Ens / best DNN / best LEAR): **NP 0.403 / 0.420 / 0.415 / 0.472; PJM 0.439 / 0.476 / 0.467 / 0.489; EPEX-BE 0.573 / 0.604 / 0.597 / 0.649; EPEX-FR 0.533 / 0.543 / 0.562 / 0.58; EPEX-DE 0.377 / 0.395 / 0.395 / 0.431**. In PJM, the LEAR ensemble improves on the best single LEAR by about 3% rMAE, and the DNN ensemble beats the LEAR ensemble by about 8%. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - Multivariate Giacomini-White tests: the DNN ensemble is significantly better than all other models in all 5 datasets, LEAR-Ens is significantly better than every individual LEAR, and individual LEARs are never significantly better than individual DNNs. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - Best-practice guidance:
    - Use test periods of at least 1 year, preferably 2 years.
    - Use rMAE, i.e. MAE relative to a seasonal naive benchmark. **MAPE is unreliable**, e.g. about 10x inflated in DE because of near-zero and negative prices.
    - RMSE "does not correctly represent the underlying problem".
    - Test significance with DM/GW.
    - Build ensembles from diverse members (different calibration windows or models), limited to **about 4-10 members** because large ensembles with heavy tails pick up outliers.
    - Compare new ensemble methods against simple averaging, not against single models.
    - DNN hyperparameter search took about 1 day on a laptop, with little gain after about 1000 iterations.
    [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
- **Weron (2014), IJF 30(4)**, "Electricity price forecasting: A review of the state-of-the-art with a look into the future". This is the foundational taxonomy (multi-agent, fundamental, reduced-form, statistical, computational intelligence). It called for probabilistic forecasting, forecast combination and better evaluation. [memory] [doi:10.1016/j.ijforecast.2014.08.008](https://doi.org/10.1016/j.ijforecast.2014.08.008)
- **Nowotarski & Weron (2018), Renewable & Sustainable Energy Reviews 81**, "Recent advances in electricity price forecasting: A review of probabilistic forecasting". It sets the probabilistic EPF framework: aim for sharpness subject to reliability, and evaluate with pinball/CRPS, PIT and Kupiec/Christoffersen tests. It surveys QRA, bootstrapping and distributional approaches. [memory] [doi:10.1016/j.rser.2017.05.234](https://doi.org/10.1016/j.rser.2017.05.234)
- **Maciejowska, Uniejewski & Weron (2022), "Forecasting electricity prices"** (encyclopedia-style review). This is an updated overview from the Wroclaw group. [arXiv 2204.11735](https://arxiv.org/pdf/2204.11735)
- **Yu et al. (2026), "Deep Learning for Electricity Price Forecasting: A Review of Day-Ahead, Intraday, and Balancing Electricity Markets"** (arXiv 2602.10071v2; authors from TU Delft, AIT, LBS, RWTH and others).
  - DA deep-learning work moved from MLP/LSTM/GRU/CNN (2018-2020) to Transformers, GNNs and MoE (2021 onward), and then to "foundation-style" multi-region models (e.g. PriceFM).
  - After 2023, many papers moved to probabilistic losses (pinball, NLL), with hierarchical quantile heads used to prevent quantile crossing.
  - The review has **no head-to-head quantitative benchmark** of LEAR vs DNN vs Transformers vs GBMs.
  - It **explicitly excludes US markets**.
  [arXiv 2602.10071](https://arxiv.org/html/2602.10071v2)

### Inferences
- LEAR-Ens vs DNN-Ens is a gap of about 2-8% rMAE across the five epftoolbox datasets, with PJM at about 8%. This is the most directly comparable number for the desk. A tuned DNN ensemble, or averaging LEAR with a DNN, would be the natural next step beyond LEAR plus a single pooled LightGBM.
- The desk's reported "-21% MAE vs yesterday's DA" corresponds to rMAE of about 0.79 against a naive-1 benchmark. epftoolbox rMAE uses naive-1 (same hour, previous day for Tue-Fri; previous week for Mon, Sat, Sun). Its PJM LEAR rMAE of about 0.47-0.49 suggests room to improve, or that NYISO zonal data is harder. Before comparing, the desk should compute rMAE exactly as epftoolbox defines it.

### Gaps
- None of the major reviews gives a quantitative synthesis for US ISO RT (5-min or hourly) LMP, or for LMP components (energy, congestion, loss).

---

## Q2. Quantitative relative performance (LEAR vs DNN vs NBEATSx vs ensembles vs DDNN vs GBM)

### Takeaway
On the epftoolbox datasets, the ranking is roughly **NBEATSx-Ens ≈ DNN-Ens > DNN > LEAR-Ens > LEAR**. The step from DNN-Ens to NBEATSx-Ens is small: about 2-5%, and not significant on PJM. For probabilistic forecasts, distributional DNNs with Johnson's SU (JSU) output beat LEAR-QRA by about 17% in CRPS and DNN-QRA by about 7% (German market). Peer-reviewed head-to-head evidence on GBMs (LightGBM/XGBoost) vs LEAR/DNN is thin.

### Cited Findings
- **Olivares, Challu, Marcjasz, Weron & Dubrawski (2023), IJF**, "Neural basis expansion analysis with exogenous variables: Forecasting electricity prices with NBEATSx". [single study; uses the epftoolbox datasets] [arXiv 2104.05522](https://arxiv.org/abs/2104.05522)
  - NBEATSx improves on the original NBEATS by about 20% and "up to 5% over other well established statistical and machine learning methods specialized" for EPF, i.e. LEAR and DNN. [arXiv 2104.05522](https://arxiv.org/abs/2104.05522)
  - Ensembled models vs the DNN ensemble: average improvements of RMSE 4.68%, MAE 2.53%, **rMAE 1.97%**, sMAPE 1.25%.
    - Significant gains: NP +5.38%, FR +2.48%, DE +2.81%.
    - **Not significant: PJM (0.24%) and BE (1.1%)**.
    [arXiv 2104.05522](https://arxiv.org/abs/2104.05522)
  - Ensembling improves NBEATSx by about 3% over its best single model. The best single NBEATSx models beat LEAR/DNN benchmarks by 0.75% to 7.2%. Inference time is milliseconds, comparable to LEAR/DNN. [arXiv 2104.05522](https://arxiv.org/abs/2104.05522)
- **Marcjasz, Narajewski, Weron & Ziel (2023), Energy Economics 125**, "Distributional neural networks for electricity price forecasting". The DDNN is a feedforward network whose output layer gives the parameters of a Normal or JSU distribution for each of the 24 hours. Market: German DA, test period includes 2020. [single study, later reused as the benchmark in several papers] [arXiv 2207.02832](https://arxiv.org/abs/2207.02832); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0140988323003419)
  - Table 1 (MAE / RMSE / CRPS):

    | Model | MAE | RMSE | CRPS |
    |---|---|---|---|
    | naive | 9.336 | 14.358 | 3.585 |
    | LEAR-Ens | 4.372 | 6.375 | – |
    | LEAR-QRA | 4.161 | 6.676 | 1.575 |
    | LEAR-QRM | 4.285 | 6.788 | 1.662 |
    | DNN-Ens | 3.610 | 5.850 | – |
    | DNN-QRA | 3.668 | 5.845 | 1.399 |
    | DNN-QRM | 3.670 | 5.821 | 1.412 |
    | DDNN-N-pEns | 3.663 | 5.962 | 1.351 |
    | DDNN-JSU-pEns | 3.542 | 6.146 | 1.304 |
    | DDNN-JSU-qEns | 3.564 | 6.174 | 1.299 |

    JSU is about 3-4% better than Normal in CRPS. The abstract reports the DDNN beating state-of-the-art benchmarks by **>7% CRPS** and by **8% in per-transaction trading profit**. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
  - **Run-to-run CRPS varies by up to 10%** for single networks, so ensembling across runs is necessary. Probability (vertical) and quantile (horizontal) averaging perform similarly. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
  - Here the gap between LEAR and DNN is large, about 16% MAE for DNN-Ens vs LEAR-Ens. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
- **Lipiecki & Weron (Aug 2026), arXiv 2609.00089**. Their benchmark implementation of LEAR+CP averages LASSO fits over windows of 56, 84, 728 and 1092 days, with λ chosen by 7-fold CV. They note this is **"more accurate" than the LARS-based λ selection in the original epftoolbox**, citing Uniejewski. In their 2021-2025 tests, DDNN-JSU was the stronger EPF-specific benchmark in CRPS than LEAR+CP in DE, PL and ES. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **GBMs**:
  - The peer-reviewed EPF benchmark literature I found does not report a controlled LightGBM/XGBoost vs LEAR/DNN comparison on the epftoolbox datasets.
  - The 2026 DL review mentions GBMs only "tangentially". [arXiv 2602.10071](https://arxiv.org/html/2602.10071v2)
  - Evidence that GBM wins comes mainly from non-peer-reviewed practitioner repositories, e.g. a Turkish DA project where a multi-window LightGBM ensemble beat epftoolbox LEAR. [GitHub](https://github.com/beratkrts/electricity-price-forecasting-turkish-day-ahead-market)
  - For ERCOT RT spike classification, one repository reports histogram gradient boosting winning over logistic regression, SVM, RF and NN on 2024 validation data. [GitHub](https://github.com/JoyZhang25/ercot-scarcity-forecasting)
  - Both are single, non-peer-reviewed sources.
- In the TSFM benchmark by Pan & Ezzat (2026), the general-purpose deep models (TFT, DeepAR, TiDE, TSMixer, DLinear, NLinear) did **not** beat the domain-specific EPF methods (LEAR, DNN, CING-LEAR) on CAISO 2025 data. TFT (Lim et al. 2021) enters only as a generic baseline, and I found no EPF-specific TFT benchmark with strong results. [arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)

### Inferences
- The desk's results match the literature. LEAR is strongest on DA totals, where fundamentals are linear-ish and hour-specific. A tree model can edge ahead on RT, where nonlinearity and regime effects matter.
- The largest documented single-step gain available is **a DNN or NBEATSx ensemble, averaged with the LEAR ensemble**: roughly 3-8% rMAE on DA in PJM-like data.
- DDNN-JSU is the documented CRPS winner among classic models, and a recent benchmark reported it as the most profitable under risk-averse trading.

### Gaps
- There is no rigorous published comparison of pooled LightGBM vs LEAR on US ISO data.
- I found no peer-reviewed EPF benchmark of TFT that beats DNN or LEAR.

---

## Q3. Probabilistic methods: which give the best CRPS and coverage?

### Takeaway
There are two families that work: (a) **postprocessing point forecasts**, using QRA and its variants, conformal prediction (CP) or isotonic distributional regression (IDR), and **combining** them; and (b) **distributional DNNs (JSU)**. The strongest published evidence (Lipiecki, Uniejewski & Weron 2024) is that an **ensemble of QRA + CP + IDR on LEAR/DNN point forecasts beats DDNN-JSU** in DE and ES over 4.5-year tests. The desk's empirical residual quantiles are essentially naive split conformal. Adding QRA over multiple point models, IDR, or adaptive CP should fix under-coverage cheaply.

### Cited Findings
- **Quantile Regression Averaging (QRA)**, Nowotarski & Weron (2015), Computational Statistics 30. QRA runs quantile regression on a pool of point forecasts. [memory] [doi:10.1007/s00180-014-0523-0](https://doi.org/10.1007/s00180-014-0523-0)
  - In Marcjasz et al. (2023), QRA on DNN point forecasts gave CRPS 1.399 vs 1.575 on LEAR, so the quality of the underlying point model dominates. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
- **LQRA (LASSO-regularized QRA)**, Uniejewski & Weron (2021), Energy Economics. It regularizes QRA when there are many input forecasts. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0140988321000268)
- **SQRA (Smoothing QRA)**, Uniejewski (and co-authors).
  - It uses kernel-smoothed quantile regression, with variants SQRA, SQRM and SQRF.
  - Across 4 markets, including the COVID and 2022 crisis periods, it did better on the Kupiec test, pinball score and CPA test than QRA-type benchmarks.
  - In a battery trading strategy it made profits "up to 9 EUR per 1 MW traded".
  - Published in a 2025 ScienceDirect journal (S2405851325000455).
  [arXiv 2302.00411](https://arxiv.org/abs/2302.00411); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2405851325000455)
- **Conformal prediction**, Kath & Ziel (2021), IJF 37: 777-799. This is the first systematic use of CP for DA and intraday power prices. [arXiv 1905.07886](https://arxiv.org/abs/1905.07886)
- **O'Connor et al. (2025)**. They apply EnbPI and SPCI (sequential predictive conformal inference), ensembled with quantile regression models, to **DA and RT balancing prices** (European, Irish-market context). They report valid, narrow intervals and higher battery-trading returns. [single study; numbers not in abstract] [arXiv 2502.04935](https://arxiv.org/abs/2502.04935); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S266654682500103X)
- **Isotonic distributional regression (IDR)**, Lipiecki, Uniejewski & Weron (2024), Energy Economics. The paper compares QRA, CP and IDR as postprocessors of point forecasts.
  - IDR "demonstrates the most varied behavior" but contributes most to the ensemble by Shapley value.
  - The combination of all three beats **DDNN** over two 4.5-year test periods (DE, ES), spanning COVID and the war in Ukraine.
  - This is the first use of IDR for EPF.
  [arXiv 2404.02270](https://arxiv.org/abs/2404.02270); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S014098832400642X)
- **Isotonic QRA (iQRA)**, Lipiecki & Uniejewski (2025, arXiv 2507.15079). iQRA adds stochastic-order constraints to QRA. On German DA prices it "consistently outperforms state-of-the-art postprocessing methods in terms of both reliability and sharpness" and gives "superior reliability to all benchmark methods, particularly coverage-based conformal prediction". The abstract gives no numeric gains. [single study] [arXiv 2507.15079](https://arxiv.org/abs/2507.15079)
- **Distributional NNs.**
  - JSU beats Normal by about 3-4% CRPS. DDNN-JSU beats DNN-QRA by about 7% and LEAR-QRA by about 17%. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
  - In 2021-2025 tests (DE, PL, ES), DDNN-JSU CRPS was 10.70, 10.96 and 9.30 respectively, which is better than LEAR+CP. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **CRPS convention warning.** Some EPF papers report the average pinball score over 99 percentiles and call it "CRPS". Such values are half the true CRPS. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **Statistical vs economic ranking can differ.**
  - The model with the lowest CRPS (TabPFN-3) did not always earn the highest battery-arbitrage profit.
  - DDNN-JSU was most profitable under risk-averse quantile strategies despite never having the lowest statistical error.
  [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- Nitka & Weron (2023), Operations Research and Decisions 33(3), ask whether minimizing CRPS when combining predictive distributions leads to optimal bidding decisions. It is cited in the source below; I have not read its conclusions. [cited in arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)

### Inferences
- There are several likely causes of the desk's under-coverage from a static empirical-residual approach: non-exchangeability (volatility regimes), no conditioning on hour or level, and pooling across hours. The literature-backed fixes, from cheapest to most involved, are:
  1. Rolling-window CP per hour, or adaptive/sequential CP (SPCI or EnbPI-style).
  2. QRA or LQRA over the pool of LEAR-window forecasts plus LightGBM forecasts.
  3. IDR.
  4. Averaging (2) and (3) with CP.
  5. A DDNN-JSU ensemble if the desk moves to neural networks.

### Gaps
- There are no published CRPS benchmarks of these postprocessors on US RT LMP.
- I did not obtain exact CRPS percentages for IDR+QRA+CP vs DDNN from the 2024 paper; only the abstract was read.

---

## Q4. Forecast combination across calibration windows and models

### Takeaway
**[Replicated, core Weron-group finding]** Averaging forecasts from the same model estimated over several calibration windows, mixing short windows of weeks and long windows of years, beats any single window and removes the need to pick a window. Averaging across model types (LEAR + DNN, or domain models + foundation models) adds further, often significant, gains.

### Cited Findings
- **Marcjasz, Serafin & Weron (2018), Energies 11(9): 2364**, "Selection of calibration windows for day-ahead electricity price forecasting".
  - The study uses six year-long datasets from three markets and four ARX expert models on raw and transformed prices.
  - There is "no universally optimal" window length.
  - Averaging across windows is robust, and the paper proposes a new weighting scheme.
  [MDPI](https://www.mdpi.com/1996-1073/11/9/2364)
- **Hubicka, Marcjasz & Weron (2019), IEEE Trans. Sustainable Energy 10(1)**, "A note on averaging day-ahead electricity price forecasts across calibration windows". Combining a few very short windows (about 28-30 days) with a few long windows (about 2 years) outperformed single windows and all-window averages. [memory] [doi:10.1109/TSTE.2018.2869557](https://doi.org/10.1109/TSTE.2018.2869557). The working paper is listed on [RePEc](https://ideas.repec.org/p/wuu/wpaper/hsc1808.html).
- **Serafin, Uniejewski & Weron (2019), Energies 12(13): 2561**, "Averaging predictive distributions across calibration windows for day-ahead electricity price forecasting". This extends window averaging to probabilistic forecasts. [MDPI/DOI](https://doi.org/10.3390/en12132561)
- The epftoolbox LEAR-Ens averages 56d, 84d, 3y and 4y windows. In PJM it improves on the best single LEAR by about 3% rMAE (0.476 vs 0.489), and it is significantly better than every individual LEAR in all 5 markets. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
- **Cross-family ensembles.** Pan & Ezzat (2026) find that a simple average of the best TSFM (Chronos-2 with covariates) and the best domain model (CING-LEAR) "achieves the strongest overall performance, yielding considerable gains over both constituent models", in both point and quantile loss, on CAISO 2025. [single study] [arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)
- Lago et al. (2021) recommend diverse ensemble members of about 4-10 models, and evaluating new combination schemes against the simple arithmetic mean. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)

### Inferences
- The desk already uses multiple LEAR windows. The next cheap step is to average LEAR-Ens and LightGBM, which are very different model types, and later a DNN or NBEATSx. On RT, this averaging may beat both models individually.

### Gaps
- There is no published evidence on window averaging specifically for US RT or congestion-component forecasting.

---

## Q5. Time-series foundation models (TSFMs) for electricity prices: evidence vs hype (2024-2026)

### Takeaway
The evidence is now reasonably rigorous (2025-2026), and it is mixed.
- **Zero-shot, univariate TSFMs (Chronos, TimesFM, Moirai, TimeGPT, Time-MoE) do not reliably beat simple seasonal models or EPF-specific models.**
- TSFMs that accept covariates (Chronos-2 with covariates, and especially **TabPFN / TabPFN-TS**) can match or beat LEAR and DDNN statistically.
- Only the TabPFN family has done so consistently, in one 5-year, 3-market study.
- The most robust gain is **averaging a TSFM with a domain model**.
- Contamination of pretraining data is a real risk when evaluating these models.

### Cited Findings
- **Hornek et al. (2025), arXiv 2506.08113.**
  - Models: Chronos-Bolt, Chronos-T5, TimesFM, Moirai, Time-MoE and TimeGPT.
  - Data: 2024 DA prices in DE, FR, NL, AT and BE, point forecasts only, no exogenous inputs, 1-year test.
  - Chronos-Bolt and Time-MoE were the best TSFMs, "on par with traditional models". **No TSFM statistically outperformed a biseasonal MSTL baseline.**
  [arXiv 2506.08113](https://arxiv.org/abs/2506.08113)
- **Pan & Ezzat (Rutgers; ICML 2026 FM4SD workshop), arXiv 2607.02623.**
  - Models: Chronos-2, TimesFM-2.5, TabPFN-TS and TOTO-1.0, zero-shot, each with and without covariates.
  - Datasets: GEFCom2014-P, and a new **CAISO "GridStatus2025"** dataset chosen to postdate TSFM pretraining.
  - Results:
    - **On GEFCom2014-P no TSFM reached the top 5 of competition entries**. The best, TOTO, ranked 8th.
    - On CAISO 2025, covariate-supported TSFMs beat statistical and general DL baselines, while covariate-free variants were "substantially worse".
    - CING-LEAR was the second-best individual model.
    - The **Chronos-2 w. + CING-LEAR average was best overall**.
    - TOTO was strong on GEFCom but degraded on 2025 data. The authors read this as a contamination warning.
  - Conclusion: domain-specific methods "remain highly competitive, especially under extreme price regimes".
  [arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)
- **Lipiecki & Weron (31 Aug 2026), arXiv 2609.00089.**
  - Scope: nine variants from five families (Chronos-2, Moirai-2, TimesFM-2.5, TabPFN, Mitra+CP), zero-shot, against LEAR+CP and DDNN-JSU. Markets DE, PL and ES, test **2021-2025**.
  - Results:
    - **Only TabPFN models consistently and significantly outperform the benchmarks** across all markets and metrics.
    - TabPFN-3 CRPS vs DDNN-JSU: DE 9.15 vs 10.70 (-14.5%), PL 9.61 vs 10.96 (-12.3%), ES 8.15 vs 9.30 (-12.4%).
    - Chronos-2 was significant only in Poland.
    - Moirai-2 and TimesFM were inconsistent.
  - Economic value: TabPFN is best under unlimited bids and riskier strategies, while DDNN-JSU is more profitable under risk-averse strategies.
  - The authors conclude that "FMs cannot universally replace market-specific models". TabPFN and Chronos-2-synth are pretrained on synthetic data only, so they carry no contamination risk.
  [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **Other studies summarized in Lipiecki & Weron (2026)**, secondary citations:
  - **Marchesi et al.**: Moirai zero-shot had worse CRPS than DDNN on BE, DE, ES and SE3 (test Oct 2023-Sep 2024). Fine-tuning helped calibration, and exogenous inputs added little.
  - **Lettner et al.**: fine-tuned Moirai and ChronosX had the best CRPS on DE-LU 2024, but NHITS+QRA came "relatively close" at far lower compute.
  - **PriceFM** (Yu et al.): a domain FM on 38 European zones with load, wind, solar and topology inputs. Gains over generic FMs were "more moderate".
  - **Ponyuenyong et al.**: Singapore RT; FMs beat ARIMA and LSTM by up to 37.4% MAPE, but against weak baselines and using MAPE.
  - **GridFM (Sayghe et al.)**: **NYISO RT 5-min LMP**, 2023-2024 test, 15.9-23.2% MAPE reduction vs TimesFM, Chronos and Moirai-MoE. It was not benchmarked against EPF-specific models.
  - ApolloPFN is proprietary; it was on par with TabPFN-TS-2.
  [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)

### Inferences
- The hype is that zero-shot TSFMs "replace" EPF models. The evidence says they don't, except for covariate-aware tabular prior-fitted networks (TabPFN), and even that rests on one strong study.
- The practical, evidence-backed use is to add TabPFN-TS or Chronos-2 with covariates as **one more ensemble member**.
- The only US-specific evidence is CAISO 2025 (DA, zero-shot) and NYISO RT (GridFM, weak baselines). Neither addresses congestion components.

### Gaps
- There is no rigorous evidence for NYISO or PJM DA or RT that compares TSFMs with LEAR and DNN.
- There is no evidence on fine-tuned TSFMs vs LEAR over multi-year US test periods.

---

## Q6. Other model families with evidence, and US nodal markets

### Takeaway
The best-supported families are the **LASSO-ARX / expert-model tradition** (Ziel, Uniejewski, Weron) and **fundamental inputs** (load, renewable forecasts, fuel and emission prices) inside statistical models. Regime-switching and jump models are mostly used to describe spot-price dynamics and medium-term risk, not as winners in DA benchmarks. The US-specific literature is small, and most of it compares ML methods against weak baselines.

### Cited Findings
- **Ziel & Weron (2018), Energy Economics 70**, "Day-ahead electricity price forecasting with high-dimensional structures: Univariate vs. multivariate modeling frameworks".
  - It compares one model for all hours (univariate) with 24 per-hour models (multivariate), using LASSO-estimated models over 12 datasets.
  - Neither framework dominates uniformly, and combining both frameworks improves accuracy.
  [memory] [doi:10.1016/j.eneco.2017.12.016](https://doi.org/10.1016/j.eneco.2017.12.016)
  - This is relevant because the desk's pooled LightGBM is "univariate" in this sense, while LEAR is "multivariate". The two are complementary.
- **Uniejewski, Nowotarski & Weron (2016), Energies 9(8): 621**, "Automated variable selection and shrinkage for day-ahead electricity price forecasting". This is the origin of LEAR-style LASSO/elastic-net ARX. [memory] [doi:10.3390/en9080621](https://doi.org/10.3390/en9080621)
- **Uniejewski, Weron & Ziel (2018), IEEE TPWRS 33(2)**, "Variance stabilizing transformations for electricity spot price forecasting". Among 16 VSTs, asinh and the probability-integral (N-PIT) transform were among the best performers. [memory] [doi:10.1109/TPWRS.2017.2734563](https://doi.org/10.1109/TPWRS.2017.2734563)
- **Mid- and long-horizon econometric models.** A 2024 arXiv study extends econometric EPF models from DA to longer horizons. [arXiv 2406.00326](https://arxiv.org/pdf/2406.00326)
- **Recent linear/NN hybrids.** "Recurrent Neural Networks with Linear Structures for Electricity Price Forecasting" (arXiv 2512.04690) and "Electricity Price Forecasting: Bridging Linear Models, Neural Networks and Online Learning" were found in search but not read. [arXiv 2512.04690](https://arxiv.org/pdf/2512.04690); [ResearchGate](https://www.researchgate.net/publication/399522373_Electricity_Price_Forecasting_Bridging_Linear_Models_Neural_Networks_and_Online_Learning)
- **CING-LEAR (Wang et al., 2026)** is a domain-specific LEAR extension. It was second-best on CAISO 2025, ahead of most TSFMs. [cited in arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)
- **US markets.**
  - The only US dataset in the epftoolbox is PJM COMED (DA, zonal, 2013-2018). [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - Pan & Ezzat (2026) use CAISO. [arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)
  - GridFM uses NYISO RT. [via arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
  - For DA-RT nodal spreads, one study found BiLSTM and Seq2Seq beating ARIMA, XGBoost, SVR and random walk. [Missouri S&T](https://scholarsmine.mst.edu/cgi/viewcontent.cgi?article=5574&context=ele_comeng_facwork)
  - ML-driven virtual bidding and DA-RT spreads: [arXiv 2104.02754](https://arxiv.org/pdf/2104.02754); [arXiv 2412.00062](https://arxiv.org/pdf/2412.00062). These are single studies and not benchmarked against LEAR.
  - The 2026 DL review explicitly excludes the US. [arXiv 2602.10071](https://arxiv.org/html/2602.10071v2)

### Inferences
- **Congestion component.** No academic benchmark shows statistical models beating persistence on LMP congestion components. The desk's result (neither model beats persistence) is not contradicted by the literature. Congestion likely needs fundamental or structural inputs: transmission outages, shift factors, constraint shadow prices, and DA-cleared flows. That points to fundamental or hybrid models rather than new statistical architectures.
- **Spike hours.** The literature (e.g. Pan & Ezzat's spike analysis) finds that domain models with covariates degrade less in spikes. A separate spike-probability classifier combined with a mixture forecast is plausible, but only weakly evidenced (the ERCOT GBM repository).
- **Regime-switching and jump models.** I found no 2020-2026 benchmark in which Markov-switching or jump models beat LEAR or DNN for DA point or probabilistic accuracy. They are better seen as tools for tail and risk modelling. This rests on absence of evidence, not on evidence against them.

### Gaps
- I found no rigorous peer-reviewed benchmarks for MISO, ERCOT or NYISO DA/RT with LEAR/DNN baselines. The same is true for functional-data models (e.g. Ziel's work on supply/demand curves), Bayesian hierarchical models and merit-order hybrids: none was located with quantitative comparisons in this session.

---

## Q7. Best practices (recalibration, feature selection, spikes and negative prices, DST, evaluation)

### Takeaway
- Recalibrate daily, using rolling windows or averages across several windows.
- Use LASSO with cross-validated λ (not LARS).
- Apply asinh or N-PIT variance-stabilizing transforms, which handle negative prices and spikes.
- Tune neural-network hyperparameters about once a year, retrain weights periodically, and ensemble 4 or more runs.
- Evaluate over test periods of 1-2+ years or longer with rMAE, CRPS and pinball, plus Kupiec/Christoffersen coverage tests, and multivariate DM/GW/CPA tests on daily 24-hour loss vectors.
- Also report economic value (e.g. battery or trading profit), since it can rank models differently.

### Cited Findings
- **Recalibration.**
  - epftoolbox LEAR is re-estimated every day on rolling windows. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - DDNN-JSU is implemented with yearly hyperparameter tuning (Optuna TPE, 4 studies × 500 trials) and weights re-estimated **every 28 days** on an expanding window. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
  - LEAR+CP uses windows of 56, 84, 728 and 1092 days, λ chosen by 7-fold CV, the asinh VST, and conformal intervals from a **1-year rolling calibration window of out-of-sample errors**. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **Negative prices and near-zero prices.** MAPE breaks down: it was about 10x inflated in EPEX-DE. Use rMAE or MAE. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004). VSTs (asinh, N-PIT) help. [memory] [doi:10.1109/TPWRS.2017.2734563](https://doi.org/10.1109/TPWRS.2017.2734563)
- **Evaluation.**
  - Test period of at least 1 year, ideally 2. rMAE vs naive. Multivariate DM/GW on daily-summed absolute losses. [arXiv 2008.08004](https://arxiv.org/abs/2008.08004)
  - The multivariate conditional predictive ability (CPA) test tailored to 24-dimensional DA forecasts. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
  - Statistical and economic evaluation beyond RMSE and MAE: Maciejowska, Lipiecki & Uniejewski (2026), Energy Conversion and Management 356. [cited in arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
  - Check the CRPS vs 2×pinball convention. [arXiv 2609.00089](https://arxiv.org/pdf/2609.00089)
- **Robustness of neural networks.** Single DDNN runs vary by up to 10% in CRPS, so always ensemble. [arXiv 2207.02832](https://arxiv.org/abs/2207.02832)
- **Contamination-aware evaluation of pretrained models.** Evaluate on data that postdates the pretraining cutoff. [arXiv 2607.02623](https://arxiv.org/pdf/2607.02623)

### Inferences
- The desk's evaluation should add three things: GW/DM (or CPA) tests on daily loss vectors, separate spike-hour and normal-hour reporting (as in Pan & Ezzat), and a trading-value metric.

### Gaps
- I found no specific published guidance on DST handling beyond common practice (e.g. averaging the duplicated hour and interpolating the missing hour, as described in the epftoolbox documentation). This was not verified in this session, so it is not a sourced claim.
- I found no peer-reviewed study on the optimal recalibration frequency for RT LMP models.
