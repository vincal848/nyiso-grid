# Congestion-component and nodal/zonal price-difference forecasting from market-participant data

Scope note: 30 tool calls; primary sources (arXiv/journal full texts) were read for Kekatos et al., Ji-Thomas-Tong, Misra-Roald-Ng, Zhou-Tesfatsion-Liu, Birge-Hortacsu-Pavlin, Leslie, Adamson-Englander. The other items were checked at abstract level only; they are marked below. "SYNTH" = results only on IEEE/PGLib test systems. "REAL" = results on real ISO data.

## 1. Learning shift factors / PTDFs / topology from market data (price-matrix factorization, inverse optimization)

### Takeaway
Theory says the congestion part of the nodal price matrix factors as (network sensitivity matrix) x (sparse shadow-price matrix). Topology recovery from prices alone (Kekatos et al.) has only been shown on synthetic grids (IEEE 30-bus). The one large real-ISO test is Birge, Hortacsu & Pavlin on MISO. It recovers constraint "utilization" (shift-factor) parameters, not physical topology, and reconstructs prices with median correlation 0.92. The desk's own OLS shift-factor result (median out-of-sample R² 0.75; low rank) is consistent with this literature and is already at about the frontier of what has been shown on real data.

### Cited Findings
- Kekatos, Giannakis & Baldick (arXiv Oct 2014; IEEE TSG 2016): real-time LMPs are the Lagrange multipliers of the dispatch LP. The spatio-temporal price matrix "factor[s] as the product of the inverse Laplacian times a sparse matrix". The sparsity comes from the few congested lines, since complementary slackness zeroes the multipliers of uncongested lines. They propose blind recovery schemes plus batch (ADMM) and online solvers for streaming prices — [arXiv 1410.6095](https://arxiv.org/abs/1410.6095); [PDF](https://arxiv.org/pdf/1410.6095)
- The Kekatos et al. validation is SYNTH only. It uses the IEEE 30-bus grid (41 lines, 20 loads) with GEFCom2012 load data scaled down 7x and perturbed with Gaussian noise to mimic 5-min variation. It reports recovered-Laplacian plots and average-degree tables, not a real ISO test. The method needs the MEC removed first: subtract the reference-bus price, or use the published MCC directly — [PDF](https://arxiv.org/pdf/1410.6095)
- Birge, Hortacsu & Pavlin, Operations Research 65(4):837-855 (2017), REAL MISO. Inverse optimization recovers "parameters of transmission and related constraints that are not revealed to market participants": per-location utilization of each constraint (shift-factor-like) and loss parameters. They explicitly do not recover physical topology. Under noise-free assumptions, identification "requires only one more data sample than there are active constraints." — [INFORMS PDF](https://epic.uchicago.edu/wp-content/uploads/sites/5/2016/12/opre.2017.1606.pdf); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2612234)
- Birge et al. results: the reconstructed dispatch uses published (anonymized) bid functions. The median correlation of predicted vs. actual MISO prices is 0.92, with the upper quartile above 0.98. The absolute price error is about 11%, attributed to data limits such as imports. MISO data from 2010-2012 — [PDF](https://epic.uchicago.edu/wp-content/uploads/sites/5/2016/12/opre.2017.1606.pdf)
- Birge et al. on binding-constraint sparsity (REAL, MISO 2012): 1,295 unique transmission lines were at capacity during the year. 89% of them bound in no more than 1% of hours, and no constraint was active in more than 30% of hours. The authors note the data "become very wide—data sets have few samples but many features." — [PDF](https://epic.uchicago.edu/wp-content/uploads/sites/5/2016/12/opre.2017.1606.pdf)
- Zhou, Tesfatsion & Liu (2011) also note that MISO (36,845 buses, 5,575 units) typically has fewer than 20 day-ahead binding constraints per hour — [working paper PDF](https://faculty.sites.iastate.edu/tesfatsi/archive/tesfatsi/WorkingPaper-CongestionForecasting.ZTL2010.pdf)
- Radovanovic, Nesti & Chen (Google; arXiv 2018, IEEE TPWRS 2019), REAL SPP (abstract level): an "OPF-principled" statistical learning approach to recover market structure from public generation mix, load and prices. The authors report DA forecasts close to an industry benchmark but acknowledge weakness on large price spikes. They do not explicitly model shift factors per constraint — [arXiv 1807.07120](https://arxiv.org/abs/1807.07120)
- Open reproduction code for "interesting facts about LMPs" / LMP inference exists, but it is not peer-reviewed — [GitHub zhengkd95/LMP-inferring](https://github.com/zhengkd95/LMP-inferring)

### Inferences
- The desk observes shadow prices by named constraint, so it does not need blind factorization. Its per-node OLS regression of MCC on shadow prices is the supervised, easier version of the Kekatos / Birge problem. The literature suggests two upgrades:
  - (a) Impose the known structure. Shift-factor matrix x sparse shadow-price vector, with a low-rank shift-factor matrix (the desk sees 8 components ≈ 90%). Fit with reduced-rank or constrained regression pooled across nodes rather than 737 separate OLS fits.
  - (b) Re-estimate per topology epoch, because shift factors change with outages.
- Birge et al.'s "one more sample than active constraints" identification only holds noise-free. With rare constraints (89% bind ≤1% of hours) many shift-factor columns will be poorly estimated. Regularizing rare-constraint columns toward the low-rank subspace spanned by frequent constraints is a natural fix. This is my inference, not tested in the sources.
- An R² of 0.75 for congestion-from-shadow-prices likely leaves residual from constraints outside the top 100, loss/energy leakage and shift-factor drift. The residual is small compared with the difficulty of forecasting the shadow prices themselves, which is where the forecasting problem really sits.

### Gaps
- No paper found that reports shift-factor recovery accuracy against true ISO shift factors on real data. Birge et al. validate by price reconstruction, not by comparison with the ISO's shift factors.
- No real-data study of low-rank-plus-sparse decomposition of ISO LMP matrices with reported forecast accuracy was found in this pass.
- The Kekatos TSG version may contain added experiments beyond the arXiv v1 that was read. This was not checked.
- Not verified: whether NYISO publishes masked bid data with enough detail and timeliness to rebuild a Birge-style dispatch. This is a data-availability question the desk should check.

## 2. Structural / multiparametric approaches (critical regions, system patterns)

### Takeaway
Multiparametric programming shows LMP and congestion are piecewise constant/affine in load/injections, with one "critical region" (system pattern) per active set. Operator-side methods (Ji-Thomas-Tong) are exact but need the full network model and offers, and were tested only on 3-bus and IEEE 118 systems. Participant-side methods (Zhou-Tesfatsion-Liu; Geng-Xie) learn the regions from historical load/price data. Only Zhou et al. has a real ISO test: NYISO 2007, 8 zones, 5 constraints, two test days, beating GARCH. That evidence is weak and old, and it collapses when the number of distinct patterns explodes, as it does in the desk's data.

### Cited Findings
- Ji, Thomas & Tong (arXiv 2015; IEEE TPWRS 2017), "Probabilistic Forecasting of Real-Time LMP and Network Congestion", written "from a system operator perspective."
  - Multiparametric program: the parameter space (load, stochastic generation) is split into critical regions, each with a unique LMP/congestion pattern (or an affine LMP map under quadratic cost). Critical regions are computed offline.
  - Online, forecasting reduces to the probability that the future parameter falls in each region.
  - Contingencies and time-varying constraints enter as a mixture over system configurations — [arXiv 1503.06171](https://arxiv.org/abs/1503.06171)
- Ji et al. test systems are SYNTH: a 3-bus system and IEEE 118-bus with 12 added wind farms. The authors say the barriers are "daunting for external market participants who do not have access to network operating conditions and confidential information on bids and offers." — [PDF](https://arxiv.org/pdf/1503.06171)
- Ji et al. scalability: the number of critical regions "may grow exponentially with the number of constraints." Their fix is dynamic critical-region generation (DCRG), which relies on "a small fraction of critical regions represent[ing] the overwhelming majority of observed critical regions." It reuses a region's affine map rather than re-solving DC-OPF, giving "several orders of magnitude" speed-up over Monte Carlo. The speed-up is computational; accuracy is identical to Monte Carlo — [PDF](https://arxiv.org/pdf/1503.06171)
- Zhou, Tesfatsion & Liu, IEEE TPWRS 26(4):2185-2196 (2011), participant perspective. A "system pattern" is the combination of line-congestion and marginal-unit flags. Historical patterns are turned into convex hulls in load space (Qhull). A point-inclusion test with a distance-ratio tolerance assigns forecast load to candidate patterns, and a per-pattern sensitivity matrix maps load to zonal LMP — [working paper PDF](https://faculty.sites.iastate.edu/tesfatsi/archive/tesfatsi/WorkingPaper-CongestionForecasting.ZTL2010.pdf); [RePEc](https://ideas.repec.org/p/isu/genstf/201101170800001091.html)
- Zhou et al. NYISO case study (REAL but tiny):
  - Setup: 2007 data; 11 zones reduced to 8; patterns built only from the 5 most frequently congested DA constraints (Dunwoodie-Shore Rd, Central East-VC, Pleasant Valley-Leeds, West Central, Sprainbrook-Egrdnctr), since marginal-unit status is not public. 32 historical patterns before the summer test day, 20 before the winter day; two test days (Aug 15 and Nov 14, 2007).
  - Accuracy: "the set of forecasted congestion patterns … always includes the actual congestion pattern," but "cannot be forecasted with high precision." RMSE, MAPE and interval loss were lower than GARCH on both days. The loss uses an accuracy-informativeness trade-off. Tolerance ε was set ad hoc (0.01 / 0.02) — [PDF](https://faculty.sites.iastate.edu/tesfatsi/archive/tesfatsi/WorkingPaper-CongestionForecasting.ZTL2010.pdf)
- Geng & Xie, IEEE TPWRS 32(2):1127-1138 (arXiv 2016; journal 2017):
  - Theory: multiparametric theory gives a unique mapping from load to LMP through "system pattern regions" (SPRs).
  - Method: SPR identification is posed as a classification problem from a market participant's viewpoint and solved with SVMs on historical load and price data, "without the knowledge of system topology and parameters".
  - Validation is SYNTH only: 3-bus and IEEE 118-bus — [arXiv 1603.07276](https://arxiv.org/abs/1603.07276); [author page](https://xb00dx.github.io/publication/2017-03-MLPLMPSVM-TPS)
- Ji et al. (2017) contrast their method with the historical-data SPR approach. Estimated SPRs are "random quantities" and give only "a heuristic estimate" of the probability distribution — [PDF](https://arxiv.org/pdf/1503.06171)

### Inferences
- The desk has 4,655 distinct binding sets in 8,760 hours. Pattern-level (whole active set) classification à la Zhou/Geng-Xie is therefore infeasible: most patterns are seen once. The structure should be factorized per constraint, i.e. predict each top constraint's binding probability and shadow price, then map to nodes through shift factors. Per-constraint models share data across patterns; per-pattern models do not.
- The multiparametric insight still matters. Within a fixed active set, LMP is affine in injections, and shadow prices are piecewise constant (linear offers) or affine (quadratic). This supports models where the shadow price depends on a flow/limit margin proxy (interface flow ÷ limit, load in a pocket) and is conditional on binding.
- Zhou et al.'s beat-GARCH-on-two-days evidence is not a meaningful benchmark by modern standards: there is no persistence baseline and no multi-month backtest.

### Gaps
- The HICSS 2015 multiparametric version (Ji, Thomas, Tong) was located but not read: [HICSS PDF](http://acsp.ece.cornell.edu/papers/JiThomasTong15HICSS.pdf). The state-space / participant-side follow-ups by Tong's group (e.g., forecasting with partial information) were not found in this pass.
- No multi-year, real-ISO backtest of any critical-region method against persistence was found.

## 3. Predicting which constraints bind (active-set classification)

### Takeaway
The ML-for-OPF active-set literature (Misra-Roald-Ng 2018/2021; Deka-Misra 2019) is entirely SYNTH. Its key premise is "low complexity": a handful of active sets carry most probability mass. That premise held for most PGLib cases (fewer than 10 relevant sets) but failed on several "adversarial" cases, where thousands of sets were discovered. The desk's real NYISO data (4,655 sets per year) sits squarely in the high-complexity regime, so direct active-set classification is unlikely to transfer. Per-constraint binary classification is the practical translation. No peer-reviewed real-ISO accuracy numbers for binding prediction were found.

### Cited Findings
- Misra, Roald & Ng, "Learning for Constrained Optimization: Identifying Optimal Active Constraint Sets" (arXiv 2018; INFORMS J. Computing 34(1), 2021/22). They learn the collection of active sets that carry most probability mass, with a streaming "DiscoverMass" stopping rule: undiscovered mass ≤ 0.05 at confidence 0.01. Once the active set is known the optimum follows by solving a linear system — [arXiv 1802.09639](https://arxiv.org/abs/1802.09639); [INFORMS](https://pubsonline.informs.org/doi/10.1287/ijoc.2020.1037)
- Misra et al. results (SYNTH, PGLib v17.08, 15 cases from 3 to 1,951 buses, load noise σ = 3% of demand):
  - Low-complexity cases: most systems have "a relatively low number of relevant active sets (< 10)" and terminate after fewer than 200 samples, even case1888/1951 rte.
  - High-complexity cases: case24/73 ieee rts and case200/240 pserc. For case240 pserc the discovery rate stayed ≥ 0.07 after 2,993 active sets were discovered, and runs hit the 22,000-sample cap.
  - Rare sets drive sample needs: "active sets with small but not insignificant probability mass (typically in the range 0.001-0.01)" — [PDF v4](https://arxiv.org/pdf/1802.09639v4)
- Deka & Misra, "Learning for DC-OPF: Classifying active sets using neural nets" (IEEE PowerTech Milan 2019; arXiv 1902.05607), SYNTH PGLib (abstract level). An NN maps the uncertainty realization to the optimal active set; they report "excellent performance" on PGLib systems — [arXiv 1902.05607](https://arxiv.org/abs/1902.05607)
- Constraint screening, i.e. predicting non-binding constraints to shrink the SCUC, is a related operator-side use of historical data — [arXiv 2312.07276](https://arxiv.org/html/2312.07276v1) (abstract level, SYNTH presumed)
- Li, Liu & Salazar, "Forecasting transmission congestion using day-ahead shadow prices" (IEEE PSCE 2006), an early participant-side use of DA shadow prices to forecast congestion. Only the title and listing were found — [ResearchGate](https://www.researchgate.net/publication/224686559_Forecasting_Transmission_Congestion_Using_Day-_Ahead_Shadow_Prices)
- Industry practice (vendor blog, not evidence of accuracy): constraint traders in PJM/MISO track unit ramps, wind forecasts and outages as leading indicators of binding constraints — [Enverus blog](https://www.enverus.com/blog/mastering-transmission-constraint-trading-in-pjm-and-miso-with-real-time-grid-analytics/)

### Inferences
- The test-system noise model (independent 3% load perturbations around one base case, fixed topology) makes the number of active sets small by construction. Real systems vary topology (outages), weather-driven injections, interchange and offers, which explains the gap to the desk's 4,655 sets.
- Recommended formulation: K separate (or multi-label) binary classifiers for the top K ≈ 50-100 constraints, P(bind_k,t | features). Evaluate with Brier score / log loss and calibration, plus PR-AUC, because positives are rare. Compare against persistence ("bound same hour yesterday / last DA") and a climatological base rate per hour-of-day/month.
- Sources state that rare sets need many samples (Misra). This implies that in the desk's data the rare constraints will not be learnable per constraint. Group them (by facility, by interface, by zone of shift-factor loading) or treat them as a residual "other congestion" term.

### Gaps
- No peer-reviewed study was found reporting binding-constraint classification accuracy (AUC/Brier) on real ISO DA or RT data. Chen et al. (as named in the brief) was not identified with certainty in this pass.
- No study was found linking active-set prediction to price-forecast skill on real data.

## 4. Shadow-price magnitude given binding; outages and interface utilization as drivers; regime models

### Takeaway
No academic papers were found that specifically model congestion shadow prices with hurdle/two-part or Markov-switching models on real ISO data; the literature here is thin. The structural results above imply a natural two-part decomposition: P(bind) x E[shadow price | bind], mapped through shift factors. Outage schedules and interface utilization are the physically motivated drivers. Their empirical value is asserted by practitioners but not quantified in peer-reviewed forecasting studies found here.

### Cited Findings
- Multiparametric theory: within a critical region, shadow prices are constant (linear costs) or affine in the parameter (quadratic costs). "each critical region is associated with a unique LMP vector" (linear case) — [Ji et al. PDF](https://arxiv.org/pdf/1503.06171)
- Ji et al. model contingencies and outages as a probability mixture over system configurations k, with critical regions {Θ_i(k)} per configuration. This is a structural template for conditioning on scheduled outages — [PDF](https://arxiv.org/pdf/1503.06171)
- Hubert, Lolas & Sircar (arXiv Jan 2026; also Energy Economics 2026), REAL NYISO, ISO-NE and ERCOT, 2015-2025:
  - Setup: predict extreme DART spread spikes with logistic regression, chosen over random forests and NNs "for robustness". Features are lagged DART, load forecasts / forecast errors and calendar; binding constraints and outages are not used as primary predictors.
  - Results: very low recall (~4-5%), with DEC precision ~0.77 vs. INC ~0.30. NYISO zonal DART correlations are "substantially weaker and more heterogeneous" than ISO-NE/ERCOT, where they are "almost perfectly correlated", meaning localized congestion matters more in NYISO. Reported NYISO P&L is $6.8M over 2022-25, $6.0M from Long Island — [arXiv 2601.05085](https://arxiv.org/html/2601.05085v1); [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0140988326004706)
- Regime-switching EPF work exists (e.g., regime-aware neural processes, 2025) but targets system price, not per-constraint congestion — [arXiv 2508.00040](https://arxiv.org/pdf/2508.00040) (abstract level)

### Inferences
- Suggested model for each top constraint k:
  - (i) Binding probability. Logistic or GBM on: interface flow/limit ratio lags, DA-vs-RT limit changes, scheduled outage indicators for elements with high shift-factor overlap, zonal load forecasts (esp. NYC/LI and upstate-downstate), wind/hydro and imports, hour/season, and DA binding status for the same hour (for RT).
  - (ii) Log shadow price given binding. Quantile regression or GBM with the same features.
  - (iii) Map to nodes via the low-rank shift factors.
  This hurdle structure directly addresses the zero-inflated target that likely defeats LEAR/LightGBM on raw MCC, where a squared loss on a mostly-zero, heavy-tailed target collapses toward persistence or zero. This is my inference and needs testing.
- Outage snapshots are the only public feature that captures the "system configuration k" in Ji et al. They should be encoded as outage-to-constraint relevance, e.g. an outage within N buses or on the same interface, or a learned outage-constraint co-occurrence matrix from history.
- DA shadow prices are the best available predictor of same-day RT binding; DA-to-RT persistence is probably the right baseline for RT congestion.

### Gaps
- No peer-reviewed hurdle/two-part or Markov-switching model of transmission shadow prices on real ISO data was found in this pass.
- No quantified evidence was found on the predictive value of scheduled transmission outages for congestion. Practitioner claims only.

## 5. Graph neural networks / spatio-temporal models for nodal price forecasting

### Takeaway
GNN nodal-LMP papers (2020-2026) mostly use IEEE-118 synthetic data or small real datasets. Their baselines are usually weak (ARIMA, plain LSTM/FNN) and they report headline improvements without strong statistical baselines such as LEAR or persistence on the congestion component. I found no evidence that GNNs beat strong baselines on real nodal congestion. Graph structure helps in zonal European settings (2026), but that is a different problem.

### Cited Findings
- Yang, Tan, Yang, Ruan & Zhong (arXiv 2021; IET Renewable Power Gen. 2022): a spectral GCN plus attention forecasts all nodal LMPs simultaneously. Tested on IEEE-118 (SYNTH) and PJM real data. The claim is that it "outperforms existing forecasting models"; baselines and numbers were not visible at abstract level — [arXiv 2107.12794](https://arxiv.org/abs/2107.12794); [IET](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/rpg2.12413)
- Chebyshev GCN for OPF LMPs (arXiv 2301.09038, 2023): SYNTH, IEEE-118 with real renewable/EV profiles. This is an OPF surrogate (it maps injections to LMP), not a forecaster; it compares against a standard GNN and an FNN — [arXiv 2301.09038](https://arxiv.org/abs/2301.09038)
- Zhang & Wu (arXiv 2020): a GAN on a 3D tensor of system-wide hourly RT LMPs, REAL SPP, public price data only. The abstract gives no accuracy numbers or baselines — [arXiv 2011.04717](https://arxiv.org/abs/2011.04717)
- Chomon & Ziel (arXiv June 2026), "Networked Spatial Effects in European EPF": 39 European bidding zones. A Networked Spatio-Temporal Model consistently beats "island-based pure local models". This is zonal Europe, not nodal congestion — [arXiv 2606.07014](https://arxiv.org/abs/2606.07014)
- A secondary summary reports T-GCN/TCN reducing MAE by 69%/61% vs. ARIMA for 1-hour-ahead prices. ARIMA is a weak baseline; source quality is unclear (aggregator snippet from [MDPI Mathematics 10(14):2366](https://doi.org/10.3390/math10142366); not read in full)
- PriceFM (arXiv 2508.04875, 2025) is a foundation model for probabilistic price forecasting across European zones. It is not nodal congestion — [arXiv 2508.04875](https://arxiv.org/pdf/2508.04875)

### Inferences
- The desk's finding that the node×constraint matrix is 8-component low rank means the spatial structure is already captured explicitly and linearly. A GNN over physical topology would mainly re-learn shift factors that the desk can estimate directly. The hard part, forecasting the shadow-price time series, is temporal/driver-based, and graph convolution does not obviously help there.
- Evidence quality is low. Common problems: synthetic data, weak baselines, no persistence comparison, no separation of the congestion component, and short test windows.

### Gaps
- No real-ISO nodal study was found that benchmarks a GNN against LEAR / GBM / persistence specifically on the congestion component (or on nodal-minus-hub spreads).

## 6. FTR/TCC valuation: expected congestion forecasting and auction price vs. realized congestion

### Takeaway
Evidence from NYISO and PJM consistently shows FTR/TCC auction prices deviate systematically from realized DA congestion. Historically they were under-priced: roughly half or less of expected value in early NYISO TCC auctions. Profits concentrate on illiquid nodal paths, and prices correct by ~10% after informed purchases are revealed. That points to information/forecasting advantages on nodal paths, not only a risk premium.

### Cited Findings
- Adamson & Englander (HICSS 2005), NYISO monthly TCCs:
  - Method: ARCH-ARMA forecasts built only on past monthly DA congestion spreads "predicted contract month conditional means and variances fairly well."
  - Auction price regression: clearing price ≈ 0.49·predicted mean − 0.098·predicted variance. After a variance-squared risk adjustment, TCC prices captured "less than 39%" of predicted mean value; "less than half of their expected spot value" — [PDF](https://www.longwoodenergy.com/sites/default/files/docs/efficiency_of_new_york_transmission_congestion_contract_auctions.pdf)
- A study using NYISO bidder-level data from June 2000 to Dec 2004 found "significant under-pricing" of TCC awards. It attributed this to risk aversion, monopsony power and winner's curse. Siddiqui et al. (2005) similarly found early (2000-01) NYISO FTR pricing highly inefficient (per search-result summaries) — [ResearchGate](https://www.researchgate.net/publication/46507078_Efficiency_and_Profit_in_the_NYISO_Transmission_Congestion_Contract_Market); [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1040619009002528)
- The Electricity Journal (2009) NYISO TCC paper (abstract level): inefficiency is greatest for contracts between dissimilar congestion zones and is linked to contract length, congestion variability and participation. Four banks earned 67% of TCC profits in 2007 — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1040619009002528)
- Leslie (Monash; working paper Dec 2018), REAL NYISO, 235 auctions from Nov 2006 to Dec 2015:
  - Who buys: retailers buy zone-indexed TCCs "at actuarially fair prices that on average equal derivative payouts". Generators and financial traders earn systematic profits only on nodal products; traders account for 51% of expenditure.
  - Where profits come from: "88% of the financial trader profits are earned from being the first firm to purchase previously illiquid products." After a profitable purchase is revealed, the price "appreciates by approximately 10%" in the next auction and the opportunity erodes. Leslie concludes premiums are "not solely due to the presence of a risk premium" — [AEA PDF](https://www.aeaweb.org/conference/2019/preliminary/paper/keh5iRB4)
- Opgrand, Preckel, Gotham & Liu, Energy Journal 43(3):33-57 (2022), REAL PJM: customers' congestion payments on average "greatly exceed auction reimbursements". Variation in ARR management strategies helps explain the gap between FTR auction price and realized value, a supply-side driver of the premium — [Energy Journal](https://journals.sagepub.com/doi/abs/10.5547/01956574.43.3.jopg); [IDEAS](https://ideas.repec.org/a/sae/enejou/v43y2022i3p33-57.html)
- PJM's 2020 FTR market review white paper is the operator's own review of FTR pricing and performance. It was not read in detail — [PJM PDF](https://www.pjm.com/-/media/DotCom/library/reports-notices/special-reports/2020/ftr-market-review-whitepaper.pdf)
- Two related works on FTR pricing and funding:
  - O'Keefe (Energy Journal 2025): unilateral market power in FTR auctions — [SAGE](https://journals.sagepub.com/doi/10.1177/01956574241303737)
  - Trieschman & Amin (arXiv Apr 2026; theoretical, no data): FTR underfunding can arise structurally from auction-vs-DAM network-model misalignment, and multi-interval FTRs carry intrinsic hedging inefficiency when DA shadow prices vary over time — [arXiv 2604.17586](https://arxiv.org/abs/2604.17586)
- Futures-implied vs. FTR-implied congestion/loss pricing shows misalignment across three North American markets (Energy Economics 2023; abstract level) — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0140988323004437)

### Inferences
- For FTR/TCC valuation, the forecast target is the sum over the period of the DA congestion spread, i.e. Σ_t Σ_k (SF_sink,k − SF_source,k)·μ_k,t. This decomposes exactly into per-constraint expected cumulative shadow prices times path shift-factor differentials. The desk's structural model therefore yields TCC valuations directly. Monthly aggregation smooths the hour-to-hour set uniqueness that hurts hourly models.
- Adamson-Englander show that even simple time-series models of monthly spreads were informative relative to early auction prices. Leslie shows remaining edge concentrates in illiquid nodal paths and decays quickly. A structural model's plausible commercial edge is in pricing illiquid nodal paths consistently, rather than zones.
- Much of this evidence is from 2000-2015. Auction efficiency has probably improved, but no recent NYISO quantification was found.

### Gaps
- No recent (post-2016) peer-reviewed NYISO TCC price vs. realized congestion study was found. PJM IMM / NYISO MMU state-of-market reports likely contain annual auction-revenue-vs-payout comparisons but were not retrieved.
- No academic paper was found that describes a full production-style FTR expected-congestion forecasting model (e.g., simulation-based production-cost models vs. statistical). Industry practice is proprietary.

## 7. Practical recommendations and pitfalls (synthesis for a public-data NYISO desk)

### Takeaway
The best-supported path is a factorized structural-statistical model:
- (i) low-rank shift factors estimated from observed shadow prices, re-estimated per topology epoch;
- (ii) per-constraint hurdle models for binding probability and shadow-price magnitude, driven by interface margins, outages, load/weather and DA information;
- (iii) nodal congestion as the shift-factor-weighted sum, validated against persistence with proper scoring rules.

Pattern/critical-region and GNN approaches have little or no real-ISO evidence and fit poorly with the desk's near-unique active sets.

### Cited Findings
- Participant-side structural forecasting is constrained by data: historical line flow and generation capacity data are "either publicly unavailable on ISO websites or only available with some delay" — [Zhou et al.](https://faculty.sites.iastate.edu/tesfatsi/archive/tesfatsi/WorkingPaper-CongestionForecasting.ZTL2010.pdf)
- Constraint binding is extremely sparse and heavy-tailed on real systems (MISO 2012: 89% of 1,295 binding lines bound in ≤1% of hours) — [Birge et al.](https://epic.uchicago.edu/wp-content/uploads/sites/5/2016/12/opre.2017.1606.pdf)
- Critical-region counts can grow exponentially with constraints, and rare active sets dominate sample complexity — [Ji et al.](https://arxiv.org/pdf/1503.06171); [Misra et al.](https://arxiv.org/pdf/1802.09639v4)
- Topology/configuration changes alter critical regions, so each configuration needs its own partition — [Ji et al.](https://arxiv.org/pdf/1503.06171)
- The Kekatos et al. factorization requires removing the energy component and depends on congested-line sparsity; it assumes lossless DC dispatch — [Kekatos et al.](https://arxiv.org/pdf/1410.6095)
- Structural reconstruction on real data leaves ~11% absolute price error even with bids, attributed to unobserved imports and similar factors — [Birge et al.](https://epic.uchicago.edu/wp-content/uploads/sites/5/2016/12/opre.2017.1606.pdf)
- In NYISO, zonal DART spreads are weakly and heterogeneously correlated, so zone- and constraint-specific modeling matters more than in ISO-NE/ERCOT — [Hubert et al. 2026](https://arxiv.org/html/2601.05085v1)

### Inferences
Recommendations. These are inferences built on the above, not directly sourced.

1. Constraint identity management.
   - Build a constraint master table that maps NYISO constraint names (monitored element + contingency) to stable facility IDs.
   - Detect renames by shift-factor signature: cosine similarity of estimated node-loading vectors between old and new names.
   - Model at the monitored-facility or interface level when contingencies vary.
2. Topology epochs.
   - Re-estimate shift factors in rolling windows or per model-update epoch, e.g. NYISO network model changes and new transmission such as major AC/DC projects.
   - Monitor drift through out-of-sample R² of MCC-from-shadow-prices by month.
3. Two-part target.
   - Model P(bind) and log(shadow price | bind) separately per top-K constraint.
   - Aggregate expected congestion as Σ_k SF_node,k·P_k·E[μ_k|bind]. For quantiles, simulate jointly, since constraints co-bind.
   - Use DA binding/shadow prices as RT features; for DA forecasting use D-1 DA and recent RT.
4. Drivers.
   - Interface flow/limit utilization and limit changes (DA vs. RT).
   - Scheduled outages mapped to constraints via historical co-occurrence.
   - Zonal load and weather forecasts, especially for load pockets (NYC/LI).
   - Wind/hydro/import schedules.
   - Calendar.
5. Validation.
   - Rolling-origin backtests over ≥1-2 years with persistence (same hour D-1 / last week), seasonal-naive and climatological baselines.
   - Score the binding classifier with Brier/log loss/calibration, and congestion or nodal spreads with MAE/pinball loss. Include the Diebold-Mariano test.
   - Report separately for the top constraints, for zero vs. non-zero hours, and for the desk's traded paths.
   - For TCC use, evaluate at monthly aggregate horizons where persistence and climatology are stronger baselines, and compare against auction clearing prices.
6. Why LEAR/LightGBM likely fail vs. persistence on raw nodal MCC.
   - Squared-loss models on a zero-inflated, heavy-tailed, 737-dimensional target with no physical structure shrink toward the mean or zero.
   - Persistence captures multi-hour/day persistence of outages and binding regimes.
   - The factorized model makes persistence one of its features rather than a competitor.

### Gaps
- No published real-ISO study was found that implements this exact factorized pipeline and reports skill vs. persistence. The desk would be doing original work; the closest real-data analogues are Birge et al. (MISO, reconstruction not forecasting) and Zhou et al. (NYISO 2007, two days, five constraints).
- The quantitative value of NYISO outage schedules for congestion forecasting is undocumented in the literature found.
