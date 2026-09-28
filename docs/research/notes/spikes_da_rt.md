# RT Price Spike Forecasting and Joint DA-RT / DART Modeling (US ISO focus, NYISO desk)

Context for the report writer: desk's LEAR/LightGBM beat persistence ~8% on average RT MAE but lose to persistence in top-5% spike hours (tail MAE ~$101-104 vs $95/MWh); empirical-residual quantiles are under-covered (90% PI covers ~88%; 98% PI covers ~95-96%). Evidence labels used below: [OOS] = out-of-sample forecast evaluation reported; [IN-SAMPLE] = fit/calibration only; [UNVERIFIED] = paper exists but its results were not retrieved in this session.

## 1. Price spike forecasting: classification + magnitude (hurdle) models, EVT, extreme quantiles, and predictors

### Takeaway
The spike literature separates *occurrence* (dynamic binary/logit, autoregressive conditional hazard, zero-inflated models) from *magnitude* (conditional distribution / EVT tails), and the strongest US-ISO evidence (NYISO/ISO-NE/ERCOT 2022-2025, OOS) found that simple regularized logistic classifiers on lagged spreads + load-forecast errors beat flexible ML (RF/GBM/NN) out of sample because spikes are too rare for flexible models to learn stably. For the NYISO desk, the physically dominant spike drivers are reserve shortages (7% of RT intervals in 2025), transmission shortages (~20% of intervals, most on Long Island), thunderstorm alerts in Con Ed territory, and unforeseen load/interchange/outage changes — all partially observable from public data.

### Cited Findings
**Occurrence models (mostly Australia NEM)**
- Christensen, Hurn & Lindsay (2009, Energy Journal 30(1):25-48), "It Never Rains but it Pours": models the persistence/clustering of spikes in electricity prices (Australia). — [SAGE](https://journals.sagepub.com/doi/10.5547/ISSN0195-6574-EJ-Vol30-No1-2)
- Christensen, Hurn & Lindsay (2012, IJF 28(2):400-411), "Forecasting spikes in electricity prices": uses dynamic logit models and autoregressive conditional hazard (ACH) models and modifications to forecast spike occurrence (Australia NEM). [OOS forecasting study; specific numeric results not retrieved] — [EconPapers](https://econpapers.repec.org/RePEc:eee:intfor:v:28:y:2012:i:2:p:400-411); [ResearchGate](https://www.researchgate.net/publication/251527885_Forecasting_Spikes_in_Electricity_Prices)
- Follow-on: "Semi-parametric forecasting of spikes in electricity prices" (Economic Record 89(287), 2013) [UNVERIFIED results]. — [IDEAS](https://ideas.repec.org/a/bla/ecorec/v89y2013i287p508-521.html)
- Eichler, Grothe, Manner & Türk (2014, Journal of Energy Markets 7(1):55-81): half-hourly spike-occurrence forecasts for Australian markets using dynamic binary response models extended with regime-specific effects and an asymmetric link function, compared against the ACH approach. [OOS comparative forecasting study] — [ResearchGate](https://www.researchgate.net/publication/257947871_Models_for_short-term_forecasting_of_spike_occurrences_in_Australian_electricity_markets_A_comparative_study)
- Manner, Türk & Eichler, "Modeling and forecasting multivariate electricity price spikes" — multivariate (interregional) spike occurrence (Australia). [UNVERIFIED details] — [PDF](https://static.uni-graz.at/fileadmin/_Persoenliche_Webseite/manner_hans/Publikationen/MannerTuerkEichlerRev.pdf)
- A 2023 Energy Economics paper proposes a zero-inflated GARX approach to electricity price spike clustering (vol 124). [UNVERIFIED results] — [IDEAS](https://ideas.repec.org/a/eee/eneeco/v124y2023ics0140988323003328.html)
- UK market: "Forecasting the occurrence of electricity price spikes in the UK power market" (Weron group working paper). [UNVERIFIED results] — [IDEAS](https://ideas.repec.org/p/wuu/wpaper/hsc1411.html)

**US ISO evidence (most relevant)**
- Hubert, Lolas & Sircar (arXiv 2601.05085; Energy Economics 2026), "Trading Electrons: Predicting DART Spread Spikes in ISO Electricity Markets": NYISO 2015-2025 (11 zones), ISO-NE 2018-2025, ERCOT 2018-2025; OOS test 2022-2025. [OOS] — [arXiv](https://arxiv.org/html/2601.05085); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0140988326004706)
  - Spike labels: DART >= $5-15/MWh (positive) or <= -$8 to -$30/MWh (negative), market-specific thresholds; separate logistic classifiers per sign per zone.
  - Features (~50 for NYISO): lagged DART (24h, 48h), zonal and system DA load forecasts, lagged zonal/system load-forecast errors, calendar/season dummies; features pooled across all 11 zones to capture cross-zonal transmission effects.
  - "More sophisticated methods (random forests, gradient boosting, neural networks) yielded marginal accuracy gains but worse out-of-sample trading performance"; logistic regression "delivered the most robust" OOS performance because spikes are rare and flexible models overfit.
  - NYISO test diagnostics: INC-side ~77% precision / ~4-5% recall; DEC-side ~30% precision / ~4-5% recall (deliberately selective).
  - NYISO cross-zone DART correlations are much weaker than ISO-NE/ERCOT (ERCOT >0.97), reflecting localized congestion — motivates zone-specific models in NYISO.
- ERCOT: an ERCOT biennial ORDC report plots price spikes against reserve capacity (2019-2023) with ORDC and Reliability Deployment Price Adders — confirming reserve level as the structural driver in an ORDC market. — [ERCOT 2024 ORDC report](https://www.ercot.com/files/docs/2024/10/31/2024-biennial-ercot-report-on-the-ordc-20241031.pdf)
- ERCOT deep learning: a Transformer model forecasts the spread between RT SCED and DAM system lambda using time info, load, solar and wind forecasts (in the context of virtual bidding). — [arXiv 2412.00062](https://arxiv.org/pdf/2412.00062)

**EVT / extreme quantiles**
- EVT (POT/GPD) is used to separate short-lived spikes as excesses over a high threshold; filtering with AR-GARCH then applying EVT to standardized residuals gives more accurate moderate and extreme tail quantiles than AR-GARCH with normal or t innovations. — [Forecasting Price Spikes in Electricity Markets (Rev. of Economic Analysis)](https://openjournals.uwaterloo.ca/index.php/rofea/article/download/1822/2096/5445); [EVT VaR for daily electricity prices, IJF](https://www.sciencedirect.com/science/article/abs/pii/S0169207005001226)
- Plain quantile regression is poorly suited to extreme conditional quantiles because of data sparsity, worsened by conditioning on exogenous covariates. — [Probabilistic net-load forecasting with conditional extremes, arXiv 2103.10335](https://arxiv.org/pdf/2103.10335)
- Australia NEM (South Australia, extreme volatility): Cornell, Dinh & Pourmousavi (arXiv 2311.07289, submitted to IJF): filtering spikes from training improves *inner* quantiles, but for *extreme outer* quantiles training on the unfiltered series is more suitable; quantile-regression-based ensemble (Q-QRA) across model classes and training-window lengths beat all constituents at all quantile levels and beat AEMO's pre-dispatch point forecasts. [OOS] — [arXiv](https://arxiv.org/pdf/2311.07289)

**NYISO spike drivers (Potomac Economics 2025 SOM, May 2026)** — [2025 SOM](https://www.potomaceconomics.com/wp-content/uploads/2026/05/NYISO-2025-SOM-Report__5-19-2026-final.pdf)
- Reserve shortages occurred in ~7% of RT intervals in 2025 and raised average LBMPs 10-15%; "most shortages are transitory and arise from rapid or unforeseen changes in load, external interchange, and other system conditions."
- Regulation shortages in 7% of intervals; system-wide and SENY 30-min reserve shortages in 2-3% of intervals; NYC zonal reserve shortages in 7% of intervals (most common zonal).
- Transmission shortages in ~20% of RT intervals, from <2% (North) to >12% (Long Island); LBMP impact from ~-$1/MWh (West) to ~$6.5/MWh (Long Island). Constraint violations are allowed when relief would cost >$200/MWh.
- "Offline GT pricing" understates transmission scarcity; correcting it would have raised Long Island average LBMP by up to $3.7/MWh in 2025.
- Thunderstorm alerts (TSAs) cut upstate-to-downstate transfer capability 1-2 GW and are modeled in RT but not DA, causing DA under-commitment downstate and DA/RT divergence; TSA congestion costs averaged $300-500/MWh in high-risk hours; 50 of 1,377 high-risk hours in 2025 accounted for 99% of TSA congestion costs. The MMU's weather-based thunderstorm forecast model showed "strong predictive accuracy," especially at high probability thresholds and high load.
- NYC 2025: transmission outages reduced combined-cycle availability and reduced supplemental commitment lowered surplus reserves, significantly raising local 10- and 30-min reserve prices.
- Long Island susceptibility: older slow-ramping steam fleet (volatility in morning/evening ramps), less intraday gas flexibility and more oil reliance, weaker transmission ties.
- Zones H&I, NYC and Long Island "are prone to high real-time price spikes when unforeseen transmission and/or generation outages occur."

### Inferences
- The desk's tail underperformance vs persistence is consistent with the literature: average-loss-trained models shrink toward the mean; spike hours are clustered (Christensen et al. "never rains but it pours"), so persistence captures clustering "for free." A hurdle design — P(spike | x) from a regularized logistic/ACH-style model with lagged spike indicators, plus a conditional magnitude model (GPD on exceedances or quantile regression trained on the unfiltered tail) — directly targets this.
- Highest-value NYISO-specific features from public data: lagged RT reserve prices / shortage indicators (NYC-10/30, SENY-30, NYCA), lagged spike indicators and time-since-last-spike, load-forecast error (lagged realized and DA forecast vs latest forecast), net-load ramp in morning/evening hours for Long Island, scheduled transmission outages affecting NYC/LI, interface limits/flows (Dysinger, Central-East, into-SENY), forecast thunderstorm probability x load for Con Ed territory, gas price level/volatility (winter), and neighbor stress (PJM/ISO-NE shortage conditions drive exports).
- Given Hubert et al., avoid expecting LightGBM to fix the tail on its own; use it for the body and a sparse, heavily regularized model for spike occurrence.

### Gaps
- Zhao, Dong, Li & Wong (2007, IEEE TPWRS spike prediction via data mining/SVM) not retrieved; results unverified.
- Lu et al. (2005, IEEE TPWRS spike forecasting) not retrieved.
- Numeric OOS results of Christensen et al. (2012) and Eichler et al. (2014) (e.g., hit rates, which model won) not retrieved.
- No published peer-reviewed study specifically forecasting NYISO RT LBMP spikes (as opposed to DART) with reserve-price features was found.
- ERCOT spike ML evidence found was mostly vendor blogs/GitHub projects (not peer-reviewed) and is excluded as evidence.

## 2. Regime-switching, jump, and self-exciting (Hawkes) models for spikes

### Takeaway
Markov regime-switching (MRS) models fit spike dynamics well in-sample — the Janczura & Weron (2010) comparison favors an independent-spike 3-regime model with time-varying transition probabilities — but their evidence is primarily in-sample goodness-of-fit; OOS forecasting evidence for MRS/jump/Hawkes models is thinner and mostly from non-US markets (Japan, Italy, New Zealand). They are better used as spike-probability features or scenario generators than as primary point forecasters.

### Cited Findings
- Janczura & Weron (2010, Energy Economics 32(5):1059-1073): calibrated a range of MRS models to spot prices; best structure = independent spike 3-regime model with time-varying transition probabilities, heteroscedastic diffusion-type base regime, and shifted spike-regime distributions. [IN-SAMPLE: calibration and goodness-of-fit comparison, not an OOS forecast horse-race] — [IDEAS](https://ideas.repec.org/a/eee/eneeco/v32y2010i5p1059-1073.html); [MPRA](https://mpra.ub.uni-muenchen.de/20661/)
- Related: Janczura & Weron, MRS with price-capped spike distributions [UNVERIFIED details]. — [MPRA](https://mpra.ub.uni-muenchen.de/23296/)
- New Zealand: Kapoor (2023, Journal of Forecasting 42(8)) analyzes and forecasts prices with regime-switching models [results UNVERIFIED]. — [Wiley](https://onlinelibrary.wiley.com/doi/full/10.1002/for.3004)
- Hawkes (Japan JEPX, Energies 2023): spikes modeled as a Hawkes process where a spike raises near-term spike intensity; variants let the intensity jump size or decay rate depend on spike magnitude; the variable-magnitude variant was effective for short-term spike-occurrence forecasts, evaluated by MAE of spike probability, weighted accuracy and Matthews correlation; also 14-day-ahead forecasts. [OOS, Japan] — [MDPI](https://www.mdpi.com/1996-1073/16/4/1570)
- Italy: fractional Brownian–Hawkes model for the Italian spot market with estimation and forecasting. [UNVERIFIED results] — [arXiv 1911.11795](https://arxiv.org/pdf/1911.11795)
- Hubert et al. (2026) motivate their approach by noting that extreme events are short-lived, clustered, and linked to binding network constraints and unexpected demand shocks — the same stylized facts motivating Hawkes models — yet chose logistic classifiers for OOS robustness. — [arXiv](https://arxiv.org/html/2601.05085)

### Inferences
- A cheap, robust way to get Hawkes/MRS benefits in the desk's model: add exponentially-decayed counts of recent spikes/shortage intervals (Hawkes-style excitation features) and a filtered MRS spike-regime probability as inputs to the classifier/quantile model, rather than forecasting with the MRS directly.
- Time-varying transition probabilities (Janczura & Weron's best spec) are essentially a logit spike model with covariates — convergent with the hurdle approach in Section 1.

### Gaps
- Cartea & Figueroa (2005, jump-diffusion with mean reversion, England & Wales) not retrieved; it is a calibration/pricing model with no OOS forecast evidence known to this search.
- No OOS horse-race of MRS vs. ML vs. hurdle models on a US ISO RT series was found.
- No Hawkes study on US ISO (NYISO/PJM/ERCOT) RT prices was found.

## 3. Joint DA-RT modeling, DART premium, and spread predictability

### Takeaway
Early US evidence (PJM, CAISO) found significant, time-varying DA forward premia, but these shrank with explicit virtual bidding (Haugom & Ullrich: PJM premia greatly reduced or eliminated; Jha & Wolak: trading costs fell significantly after CAISO convergence bidding). Nevertheless, NYISO DART remains partially predictable in the tails from public data (Hubert et al. 2022-2025 OOS profits, concentrated in stress events, esp. Long Island), and the NYISO MMU documents structural sources of predictable divergence (TSA constraints modeled only in RT, reserve shortages, load under-scheduling). Direct joint-distribution (copula/multivariate) work exists mainly for European coupled DA markets, not DA-RT pairs.

### Cited Findings
**Premia and convergence (US)**
- Longstaff & Wang (2004, Journal of Finance): hourly PJM spot and DA forward prices; significant forward risk premia that vary through the day and relate to volatility of unexpected demand changes, spot prices and total revenues; positive premia in highest-demand hours, negative in low-load hours. [IN-SAMPLE regression evidence, PJM ~2000] — [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00682.x); [UCLA PDF](https://www.anderson.ucla.edu/documents/areas/fac/finance/file4.pdf)
- Haugom & Ullrich (2012, Energy Economics), "Market efficiency and risk premia in short-term forward prices" (PJM): short-term forward prices have converged toward unbiased predictors of spot; PJM premia greatly reduced or eliminated in more recent years; premia vary with market conditions (supply-demand imbalance, regulation, fuel). — [ResearchGate](https://www.researchgate.net/publication/256967928_Market_efficiency_and_risk_premia_in_short-term_forward_prices)
- Jha & Wolak (working paper 2013; later published): develop tests of the null that profitable DA-RT trading strategies exist net of transaction costs, over portfolios of 24 hourly spreads, on CAISO nodal LMPs; all trading-cost measures significantly smaller after explicit convergence bidding (Feb 2011); pre-CB generation nodes had lower trading costs, but the gap vanished after CB; CB also reduced fossil fuel input and variable cost. — [Stanford PDF](https://web.stanford.edu/group/fwolak/cgi-bin/sites/default/files/files/CAISO_VB_draft_V8.pdf); [J. Regulatory Economics related paper](https://link.springer.com/article/10.1007/s11149-015-9281-3)
- Day-ahead forward premiums have also been studied for ERCOT (Texas). [UNVERIFIED results] — [ResearchGate](https://www.researchgate.net/publication/305192259_Day-ahead_forward_premiums_in_the_Texas_electricity_market)

**NYISO convergence facts (2025 SOM)** — [Potomac Economics 2025 SOM](https://www.potomaceconomics.com/wp-content/uploads/2026/05/NYISO-2025-SOM-Report__5-19-2026-final.pdf)
- 2025: DA exceeded RT by 0.4-2.3% in West through Capital zones; Central had a small RT premium (0.7%); all Southeast NY zones had RT > DA on average: NYC RT premium 4.7%, Long Island 5.6%, driven by severe RT reserve shortages in summer heat waves and RT congestion. RT premia largest in June-July; DA premia largest in January and December (gas price and volatility highest).
- Net DA scheduled load ~96% of actual NYCA load in daily peak hours (under-scheduling), but net scheduling is highest in Zones H&I, NYC and Long Island, where RT spikes are most likely.
- Virtual traders netted ~$1.8M in 2024 and ~$30.3M in 2025; internal-zone virtuals earned $45.8M in 2025 while interface virtuals lost $15.5M; average virtual profitability $1.02/MWh. The MMU notes profits/losses vary over time "reflecting the difficulty of predicting volatile real-time prices."
- Virtual traders historically correct TSA-driven divergence by buying load downstate and selling upstate.

**DART predictability from public info (US, OOS)**
- Hubert, Lolas & Sircar (2026): logistic DART-spike classifiers + a price-impact model (impact calibrated from DA bid-stack slopes) produced ~$5.76M cumulative P&L net of price impact across NYISO zones 2022-2025 (Long Island ~$6.0M, NYC ~$0.73M; smaller zones like Millwood and Genesee lost money); a majority of gains came from one episode (June 24, 2025 heat wave); authors say profits may be compensation for tail risk and whether they are risk premium or systematic forecast error "remains an open question." NYISO Summer Peak buy-side impact ~$34.6-46.5/MWh per 1,000 MWh; realized June 24, 2025 impacts $8-41/MWh per 1,000 MWh. [OOS] — [arXiv](https://arxiv.org/html/2601.05085)
- A Bi-LSTM Seq2Seq architecture has been used to forecast nodal DA-RT price differences (PJM) for virtual bidding. [UNVERIFIED results] — [arXiv 2412.00062](https://arxiv.org/pdf/2412.00062); [ResearchGate figure](https://www.researchgate.net/figure/Actual-and-forecasted-DA-RT-market-price-difference-using-PJM-market-data-from-Oct-31_fig1_356867609)
- Machine learning analytics for virtual bidding (IJEPES, 2022). [UNVERIFIED results] — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S014206152200494X)
- Algorithmic virtual bidding portfolio work (Wang/Tong et al., arXiv 1802.03010). [UNVERIFIED details] — [ar5iv](https://ar5iv.labs.arxiv.org/html/1802.03010)
- Generative probabilistic forecasting of RT market signals (interpretable generative AI, arXiv 2403.05743) — includes probabilistic RT LMP / spread forecasting in US markets. [UNVERIFIED details] — [arXiv](https://arxiv.org/pdf/2403.05743)

**Joint-distribution methods (mostly Europe DA)**
- Pircalabu & Benth (2017, Energy Economics 68): regime-switching AR-GARCH copula for pairs of DA prices in coupled markets (DE-FR, DE-NL, NL-BE, DE-DK1); skew-t marginals beat normal; significant tail dependence; applications to FTR pricing and OOS tail-quantile forecasting. [OOS tail quantiles] — [IDEAS](https://ideas.repec.org/a/eee/eneeco/v68y2017icp283-302.html)
- Dynamic vine copulae with time-varying dependence give accurate one-day-ahead conditional quantiles for interconnected Australian regional prices. [OOS] — [Academia](https://www.academia.edu/107662657/Forecasting_the_joint_distribution_of_Australian_electricity_prices_using_dynamic_vine_copulae)
- Schaake shuffle for turning point/marginal forecasts into multivariate (across hours) probabilistic DA price forecasts (Energy Economics 2023). [UNVERIFIED numbers] — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0140988323001007)

### Inferences
- Model the spread directly for DART decisions: DA prices are relatively smooth and forecastable; almost all DART tail risk comes from RT. A practical joint design: (a) marginal DA forecast (desk's existing LEAR/LGBM), (b) direct conditional distribution of DART = DA - RT (quantile/distributional model with spike hurdle), (c) implied RT = DA - DART; or a copula (e.g., skew-t marginals + t/vine copula with regime-dependent tail dependence) linking DA and RT residuals. The difference-of-two-forecasts approach discards the strong positive DA/RT error correlation and tends to overstate spread variance in normal hours while understating tail dependence in stress hours (inference, not directly tested in retrieved sources).
- Sign conventions: MMU and Hubert et al. both find downstate (NYC/LI) RT premia and profitable DEC-side positions on Long Island — expect the conditional DART distribution there to be left-skewed (RT spikes) in summer peak hours and DA-premium in winter gas-volatile months.
- Evaluate joint forecasts by DART-trade P&L net of estimated price impact, not only by CRPS; Hubert et al. show forecast accuracy and trading profit rankings can disagree.

### Gaps
- Bowden, Hu & Payne (on MISO/US DA-RT forward premia and day-of-week/hour effects) not retrieved.
- No study found that fits a copula specifically to DA and RT prices at the same US ISO node/zone with OOS evaluation.
- No peer-reviewed NYISO-specific evidence on the DART premium's predictability from reserve prices or outage schedules (beyond MMU descriptive analysis and Hubert et al.) was found.
- Published Jha & Wolak numeric trading-cost estimates ($/MWh) not extracted.

## 4. Probabilistic calibration for heavy tails (conformal, QRA, heavy-tailed distributional regression, evaluation)

### Takeaway
Conformal methods adapted to time series (EnbPI, SPCI, adaptive CP) consistently fix coverage shortfalls that quantile regression/QRA exhibit, at the cost of wider intervals; ensembles of QR + conformal get both good width and coverage. Distributional models with Johnson SU outputs beat Gaussian and QRA benchmarks on CRPS (~7%) and trading profit (~8%) in Germany. For extreme tails, EVT or training on unfiltered data is needed; raw QR is data-starved at 0.98-0.99.

### Cited Findings
- Kath & Ziel (2021, IJF): first application of conformal prediction to short-term electricity price forecasting; compared with QRA and other state-of-the-art EPF models in an OOS study on three short-term electricity price series (DA and intraday). [OOS] — [arXiv 1905.07886](https://arxiv.org/abs/1905.07886)
- O'Connor, Bahloul, Rossi, Prestwich & Visentin (arXiv 2502.04935, 2025): Irish DA and real-time Balancing Market; compared QR, QRA, QRA-CP, split CP, EnbPI, SPCI and an ensemble Q-Ens. QR/QRA were efficient (narrow) but "fell short in coverage," whereas CP methods (SCP, EnbPI, SPCI) excelled in coverage; the QR+CP ensemble achieved narrow intervals and high coverage and the best battery-trading returns in both DA and balancing markets. Authors flag robustness to outliers/non-exchangeability and extreme price events as open problems. [OOS] — [arXiv](https://arxiv.org/pdf/2502.04935); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S266654682500103X)
- Adaptive conformal predictions for time series (Zaffran et al., arXiv 2202.07282) — adaptive CP that updates the miscoverage rate online, applied to French electricity spot prices. [OOS; details UNVERIFIED in this session] — [arXiv](https://arxiv.org/pdf/2202.07282)
- Marcjasz, Narajewski, Weron & Ziel (2023, Energy Economics): distributional DNN outputting Normal or Johnson SU parameters; German DA prices; outperforms state-of-the-art benchmarks by >7% CRPS and 8% per-transaction trading profit. [OOS] — [arXiv 2207.02832](https://arxiv.org/abs/2207.02832); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0140988323003419)
- Factor-QRA hybrid for probabilistic forecasting applied to electricity trading (arXiv 2303.08565). [UNVERIFIED numbers] — [arXiv](https://arxiv.org/pdf/2303.08565)
- Cornell et al. (NEM): unfiltered training is better for extreme outer quantiles; ensembles across training-window lengths improve adaptivity. [OOS] — [arXiv 2311.07289](https://arxiv.org/pdf/2311.07289)
- Pircalabu & Benth (2017): skew-t marginals clearly better than normal for DA price pairs. — [IDEAS](https://ideas.repec.org/a/eee/eneeco/v68y2017icp283-302.html)
- AR-GARCH + EVT on standardized residuals gives more accurate moderate and extreme tail quantiles than normal- or t-innovation GARCH. — [IJF 2005 (Chan & Gray)](https://www.sciencedirect.com/science/article/abs/pii/S0169207005001226)
- Review of probabilistic price forecasting across DA, intraday and balancing markets (arXiv 2511.05523, 2025). — [arXiv](https://arxiv.org/pdf/2511.05523)

### Inferences
- The desk's 88%/95-96% coverage at nominal 90%/98% is the typical symptom of static empirical-residual quantiles under non-exchangeable, regime-dependent errors. Low-effort fixes in order: (1) adaptive conformal (ACI / SPCI) with a rolling or weighted calibration window; (2) conformalized quantile regression on a *spike-aware* base model so interval width scales with conditional risk (reserve margin, TSA probability, lagged shortage); (3) condition calibration on regime (e.g., separate calibration sets for summer peak hours/high-load days, or Mondrian CP by zone x season x spike-probability bucket) to fix conditional, not just marginal, coverage in the tail.
- For 0.98-0.99 quantiles, splice a GPD tail on exceedances above a conditional ~0.9 quantile (EVT-over-QR) rather than extrapolating QR/LightGBM quantile loss.
- Evaluation set: pinball loss at 0.9/0.95/0.98/0.99, CRPS plus threshold- or quantile-weighted CRPS emphasizing the upper tail, PIT histograms/reliability diagrams computed separately for spike and non-spike regimes, Kupiec/Christoffersen coverage tests, and Brier score / reliability for the spike classifier. (Tail-weighted CRPS and Kupiec tests are standard practice; no retrieved source applied them to NYISO.)

### Gaps
- No study found applying conformal prediction to US ISO RT LMPs with tail-specific coverage evaluation.
- Johnson SU vs skewed-t head-to-head on RT (5-min/hourly) US prices not found; Marcjasz et al. is DA Germany only.
- Tail-weighted CRPS applications in electricity price forecasting were not retrieved.

## 5. NYISO specifics: shortage pricing, reserve demand curves, load pockets, MMU analysis

### Takeaway
NYISO's ORDC values are low relative to neighbors (NYISO $750-3,000/MWh even in deep shortages vs $4,000-12,000/MWh in ISO-NE/PJM), so NYISO RT spikes are mostly frequent, moderate, transitory shortage-price adders plus local congestion (NYC reserves, Long Island transmission shortages, TSA constraints), rather than rare cap-level events. This makes spike magnitude somewhat bounded/stepwise by ORDC segments, which is exploitable in a magnitude model.

### Cited Findings (all from Potomac Economics 2025 SOM unless noted) — [2025 SOM](https://www.potomaceconomics.com/wp-content/uploads/2026/05/NYISO-2025-SOM-Report__5-19-2026-final.pdf)
- NYISO shortage prices: $750-3,000/MWh even in deep shortages vs $4,000-12,000/MWh in ISO-NE and PJM during relatively small shortages; disparity incentivizes exports from NY during local shortages, especially during gas scarcity. MMU recommends raising reserve demand curves (Rec. 2017-2).
- Deep 30-min reserve shortage in NYISO incl. locational adders approaches ~$1,000/MWh vs ISO-NE ~$10,600/MWh; deep multi-product (30-min + 10-min) shortages can exceed $2,000/MWh vs ~$3,500 (PJM) and >$12,000 (ISO-NE).
- Most LBMP impact of shortage pricing comes from low-value ORDC segments; high-value segments (e.g., $500-775/MWh) exist for system, Eastern NY and SENY requirements.
- 10-min ORDC: combined current value $1,525/MWh (10-min spin + 10-min total); MMU's EVOLL estimate exceeds $16,000/MWh near depletion; ORDC undervalues reserves below ~600 MW but overvalues from ~800 MW up to the 1,310 MW requirement. 30-min: current $750/MWh vs EVOLL ~$2,800/MWh near depletion; undervalued at or below ~725 MW; 30-min requirement 2,620 MW.
- Reserve shortages ~7% of RT intervals in 2025, +10-15% on average LBMPs; NYC zonal reserve shortages 7% of intervals; 2025 increase driven by higher gas prices, RGGI prices, exports to Quebec, reduced hydro, and transmission outages limiting low-cost NYC generation.
- Dynamic Reserve project targeted for 2028 (MMU sees design deficiencies) — a future structural break for reserve-price features.
- Earlier NYISO reserve demand curve design documentation (e.g., $605/MWh example total reserve price for a NYC 30-min unit under a 50 MW multi-region 30-min shortage via nested constraints). — [NYISO, Implementing Reserve Demand Curves](https://www.nyiso.com/documents/20142/1405484/reserve_demand_curve.pdf/9576bb22-5594-9ab1-0a56-7a72759d3c96)
- Potomac Economics also reported sharp RT congestion spikes during the June 2025 heat wave driven by high load, generation deratings/outages, and stressed neighboring markets not fully anticipated in DA (Q2 2025 quarterly report). — [Q2 2025 Quarterly Report](https://www.potomaceconomics.com/wp-content/uploads/2025/08/NYISO-Quarterly-Report_2025Q2_9-25-2025-revised.pdf)
- Survey of reserve and energy scarcity pricing across US markets (OSTI). [UNVERIFIED details] — [OSTI](https://www.osti.gov/pages/servlets/purl/2424806)

### Inferences
- Because NYISO RT spikes are largely ORDC-step and local-congestion driven, a magnitude model can be semi-structural: predicted price = base energy price + P(shortage of product k) x ORDC step value + congestion component. Lagged RT reserve (ancillary) prices by product/location are likely the single most informative public spike feature, and ORDC changes (and 2028 Dynamic Reserve) must be treated as regime breaks.
- The June 24, 2025 heat wave is simultaneously the dominant DART P&L event (Hubert et al.) and a severe shortage/congestion event (MMU) — any backtest of tail models should report results with and without it to avoid single-event overfitting.
- TSA-probability x load is a public-data-derivable, MMU-validated predictor of downstate RT congestion spikes and DA/RT divergence; a desk can replicate a thunderstorm-probability feature from weather forecasts.

### Gaps
- MMU appendix detail (Section V.G, ORDC simulation; Appendix I.H monthly convergence) not extracted.
- No quantitative MMU attribution of RT spikes to load-forecast error vs outages vs interchange was found; MMU states qualitatively that most shortages arise from rapid/unforeseen changes in load, interchange and system conditions.
- 5-minute vs hourly-integrated RT spike behavior in NYISO not investigated here.
