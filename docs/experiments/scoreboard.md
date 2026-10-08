# Validation scoreboard (anchor horizon h0)

_Generated 2026-10-05 00:38 by `lmp report`._

- Forecast: hourly DA and RT prices for delivery day D, issued 05:00 ET on D−1; 15 NYISO zones (11 internal + 4 external proxies).
- Validation: 2022-10-01 → 2025-10-01 (exclusive), monthly rolling-origin folds, expanding window from 2021-10-01, 7-day embargo. Holdout 2025-10-01 → 2026-10-01 is spent (opened once, for M7); scores here are validation only.
- **Primary metrics: CRPS (whole distribution) and RMSE (conditional mean).** MAE is secondary: it rewards the median, and for zero-inflated targets such as congestion an always-zero forecast can win on MAE while being useless for trading. Tables are sorted by CRPS.
- rMAE = MAE / MAE of `lago_naive` on the same rows. CRPS from 21 stored quantiles (models whose quantiles come from their own out-of-sample errors have none in the first fold, so their CRPS covers folds 2..36). RT hours flagged in `rt_flag` are not scored.
- Components are additive: total = energy + loss + congestion (congestion = −MCC).

## Pooled validation metrics

| model | market | component | n | mae | rmae | rmse | smape | normal_mae | tail_mae | crps | cov50 | cov90 | cov98 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| combo3wx_eq_aci | da | congestion | 394,560 | 3.484 | 0.803 | 8.972 | 1.514 | 2.433 | 23.464 | 2.739 | 0.504 | 0.903 | 0.973 |
| assemble_v1_final | da | congestion | 394,560 | 3.539 | 0.816 | 9.444 | 1.522 | 2.346 | 26.219 | 2.743 | 0.506 | 0.903 | 0.973 |
| lear2_long_aci | da | congestion | 394,560 | 3.539 | 0.816 | 9.444 | 1.522 | 2.346 | 26.219 | 2.743 | 0.506 | 0.903 | 0.973 |
| combo2_inv_aci | da | congestion | 394,560 | 3.579 | 0.825 | 9.114 | 1.514 | 2.460 | 24.826 | 2.768 | 0.503 | 0.903 | 0.973 |
| assemble_v1e_v2c_aci | da | congestion | 394,560 | 3.534 | 0.815 | 9.424 | 1.525 | 2.334 | 26.349 | 2.770 | 0.506 | 0.904 | 0.973 |
| lear2_aci | da | congestion | 394,560 | 3.534 | 0.815 | 9.424 | 1.525 | 2.334 | 26.349 | 2.770 | 0.506 | 0.904 | 0.973 |
| combo3_eq_aci | da | congestion | 394,560 | 3.511 | 0.809 | 9.151 | 1.519 | 2.415 | 24.331 | 2.778 | 0.502 | 0.903 | 0.973 |
| combo2_eq_aci | da | congestion | 394,560 | 3.593 | 0.828 | 9.125 | 1.514 | 2.479 | 24.755 | 2.779 | 0.504 | 0.903 | 0.973 |
| lear_wx_clip_aci | da | congestion | 394,560 | 3.555 | 0.819 | 9.510 | 1.547 | 2.395 | 25.597 | 2.836 | 0.504 | 0.904 | 0.974 |
| lear_clip_aci | da | congestion | 394,560 | 3.621 | 0.834 | 9.891 | 1.551 | 2.433 | 26.177 | 2.897 | 0.504 | 0.903 | 0.974 |
| lear2 | da | congestion | 394,560 | 3.534 | 0.815 | 9.424 | 1.525 | 2.334 | 26.349 | 2.901 | 0.562 | 0.897 | 0.964 |
| lear_wx | da | congestion | 394,560 | 3.555 | 0.819 | 9.510 | 1.547 | 2.395 | 25.597 | 2.952 | 0.588 | 0.901 | 0.968 |
| lear_wx_clip | da | congestion | 394,560 | 3.555 | 0.819 | 9.510 | 1.547 | 2.395 | 25.597 | 2.952 | 0.588 | 0.901 | 0.968 |
| lear_clip | da | congestion | 394,560 | 3.621 | 0.834 | 9.891 | 1.551 | 2.433 | 26.177 | 3.017 | 0.586 | 0.901 | 0.967 |
| struct_cong | da | congestion | 394,560 | 3.471 | 0.800 | 10.892 | 1.426 | 2.130 | 28.951 | 3.069 | 0.663 | 0.900 | 0.961 |
| gbm_l1_v3_aci | da | congestion | 394,560 | 4.013 | 0.925 | 9.765 | 1.538 | 2.960 | 24.004 | 3.113 | 0.504 | 0.902 | 0.971 |
| gbm_l1_aci | da | congestion | 394,560 | 4.004 | 0.923 | 9.868 | 1.542 | 2.897 | 25.037 | 3.124 | 0.503 | 0.902 | 0.972 |
| struct_cong_out | da | congestion | 394,560 | 3.537 | 0.815 | 11.563 | 1.428 | 2.177 | 29.374 | 3.135 | 0.658 | 0.898 | 0.961 |
| lear | da | congestion | 394,560 | 3.760 | 0.867 | 21.462 | 1.553 | 2.528 | 27.168 | 3.139 | 0.586 | 0.901 | 0.968 |
| persist_da_d1 | da | congestion | 394,560 | 3.602 | 0.830 | 10.870 | 1.283 | 2.445 | 25.595 | 3.183 | 0.663 | 0.912 | 0.976 |
| gbm_l1_v3 | da | congestion | 394,560 | 4.013 | 0.925 | 9.765 | 1.538 | 2.960 | 24.004 | 3.328 | 0.541 | 0.891 | 0.957 |
| gbm_l1 | da | congestion | 394,560 | 4.004 | 0.923 | 9.868 | 1.542 | 2.897 | 25.037 | 3.333 | 0.552 | 0.893 | 0.960 |
| struct_cong_l2 | da | congestion | 394,560 | 4.066 | 0.937 | 10.440 | 1.549 | 2.948 | 25.314 | 3.387 | 0.528 | 0.887 | 0.958 |
| zero_congestion | da | congestion | 394,560 | 4.690 | 1.081 | 14.294 | 2.000 | 2.193 | 52.121 | 3.787 | 0.677 | 0.901 | 0.963 |
| gbm_l2 | da | congestion | 394,560 | 4.751 | 1.095 | 10.764 | 1.545 | 3.747 | 23.839 | 3.793 | 0.552 | 0.887 | 0.958 |
| lago_naive | da | congestion | 394,560 | 4.339 | 1.000 | 12.634 | 1.380 | 2.992 | 29.921 | 3.830 | 0.664 | 0.913 | 0.977 |
| weekly_da_d7 | da | congestion | 394,560 | 5.430 | 1.251 | 15.084 | 1.516 | 3.766 | 37.043 | 4.746 | 0.663 | 0.911 | 0.978 |
| persist_rt_d2 | da | congestion | 394,560 | 6.420 | 1.480 | 28.947 | 1.639 | 4.349 | 45.761 | 5.728 | 0.660 | 0.912 | 0.975 |
| combo3wx_eq_aci | da | energy | 394,560 | 5.712 | 0.591 | 12.726 | 0.158 | 4.149 | 35.400 | 4.404 | 0.499 | 0.901 | 0.973 |
| assemble_v1e_v2c_aci | da | energy | 394,560 | 5.718 | 0.592 | 11.794 | 0.181 | 4.345 | 31.804 | 4.426 | 0.502 | 0.903 | 0.973 |
| lear_clip_aci | da | energy | 394,560 | 5.718 | 0.592 | 11.794 | 0.181 | 4.345 | 31.804 | 4.426 | 0.502 | 0.903 | 0.973 |
| lear_wx_clip_aci | da | energy | 394,560 | 5.740 | 0.594 | 11.768 | 0.177 | 4.326 | 32.600 | 4.468 | 0.502 | 0.903 | 0.973 |
| assemble_v1_final | da | energy | 394,560 | 5.868 | 0.607 | 12.824 | 0.164 | 4.286 | 35.912 | 4.491 | 0.500 | 0.902 | 0.972 |
| combo3_eq_aci | da | energy | 394,560 | 5.868 | 0.607 | 12.824 | 0.164 | 4.286 | 35.912 | 4.491 | 0.500 | 0.902 | 0.972 |
| lear_clip | da | energy | 394,560 | 5.718 | 0.592 | 11.794 | 0.181 | 4.345 | 31.804 | 4.526 | 0.539 | 0.895 | 0.963 |
| lear_wx_clip | da | energy | 394,560 | 5.740 | 0.594 | 11.768 | 0.177 | 4.326 | 32.600 | 4.564 | 0.537 | 0.892 | 0.963 |
| lear_wx | da | energy | 394,560 | 5.740 | 0.594 | 11.768 | 0.177 | 4.326 | 32.600 | 4.564 | 0.537 | 0.892 | 0.963 |
| lear | da | energy | 394,560 | 5.813 | 0.602 | 12.179 | 0.182 | 4.396 | 32.738 | 4.613 | 0.540 | 0.897 | 0.963 |
| lear2_long_aci | da | energy | 394,560 | 5.921 | 0.613 | 12.413 | 0.176 | 4.421 | 34.408 | 4.652 | 0.501 | 0.903 | 0.972 |
| lear2_aci | da | energy | 394,560 | 6.043 | 0.626 | 13.155 | 0.171 | 4.417 | 36.911 | 4.779 | 0.499 | 0.902 | 0.972 |
| combo2_inv_aci | da | energy | 394,560 | 6.152 | 0.637 | 13.918 | 0.168 | 4.400 | 39.428 | 4.792 | 0.499 | 0.902 | 0.971 |
| combo2_eq_aci | da | energy | 394,560 | 6.240 | 0.646 | 14.154 | 0.170 | 4.455 | 40.154 | 4.846 | 0.499 | 0.902 | 0.971 |
| lear2 | da | energy | 394,560 | 6.043 | 0.626 | 13.155 | 0.171 | 4.417 | 36.911 | 4.898 | 0.527 | 0.888 | 0.961 |
| gbm_l1_v3_aci | da | energy | 394,560 | 7.208 | 0.746 | 15.927 | 0.197 | 5.293 | 43.563 | 5.475 | 0.499 | 0.901 | 0.971 |
| gbm_l1_aci | da | energy | 394,560 | 7.552 | 0.782 | 16.587 | 0.205 | 5.494 | 46.641 | 5.681 | 0.500 | 0.901 | 0.970 |
| gbm_l1_v3 | da | energy | 394,560 | 7.208 | 0.746 | 15.927 | 0.197 | 5.293 | 43.563 | 5.706 | 0.517 | 0.883 | 0.955 |
| gbm_l1 | da | energy | 394,560 | 7.552 | 0.782 | 16.587 | 0.205 | 5.494 | 46.641 | 5.893 | 0.529 | 0.887 | 0.956 |
| persist_da_d1 | da | energy | 394,560 | 7.640 | 0.791 | 16.480 | 0.204 | 5.942 | 39.881 | 6.240 | 0.528 | 0.899 | 0.970 |
| gbm_l2 | da | energy | 394,560 | 8.193 | 0.848 | 16.079 | 0.228 | 6.373 | 42.762 | 6.402 | 0.521 | 0.883 | 0.949 |
| lago_naive | da | energy | 394,560 | 9.660 | 1.000 | 22.512 | 0.245 | 7.616 | 48.468 | 8.005 | 0.526 | 0.899 | 0.972 |
| weekly_da_d7 | da | energy | 394,560 | 13.645 | 1.413 | 28.707 | 0.324 | 10.836 | 67.000 | 11.224 | 0.526 | 0.891 | 0.967 |
| persist_rt_d2 | da | energy | 394,560 | 14.360 | 1.487 | 42.950 | 0.363 | 11.173 | 74.879 | 11.780 | 0.537 | 0.897 | 0.968 |
| combo3wx_eq_aci | da | loss | 394,560 | 0.481 | 0.648 | 1.000 | 0.471 | 0.375 | 2.490 | 0.371 | 0.498 | 0.900 | 0.973 |
| assemble_v1_final | da | loss | 394,560 | 0.490 | 0.660 | 1.006 | 0.480 | 0.383 | 2.518 | 0.377 | 0.499 | 0.900 | 0.973 |
| combo3_eq_aci | da | loss | 394,560 | 0.490 | 0.660 | 1.006 | 0.480 | 0.383 | 2.518 | 0.377 | 0.499 | 0.900 | 0.973 |
| lear_wx_clip_aci | da | loss | 394,560 | 0.504 | 0.679 | 1.009 | 0.508 | 0.395 | 2.571 | 0.387 | 0.498 | 0.901 | 0.973 |
| assemble_v1e_v2c_aci | da | loss | 394,560 | 0.507 | 0.683 | 1.016 | 0.513 | 0.397 | 2.592 | 0.390 | 0.499 | 0.901 | 0.973 |
| lear_clip_aci | da | loss | 394,560 | 0.507 | 0.683 | 1.016 | 0.513 | 0.397 | 2.592 | 0.390 | 0.499 | 0.901 | 0.973 |
| combo2_eq_aci | da | loss | 394,560 | 0.508 | 0.684 | 1.063 | 0.490 | 0.392 | 2.714 | 0.393 | 0.497 | 0.900 | 0.972 |
| combo2_inv_aci | da | loss | 394,560 | 0.508 | 0.684 | 1.063 | 0.490 | 0.391 | 2.717 | 0.393 | 0.497 | 0.900 | 0.972 |
| lear_wx | da | loss | 394,560 | 0.504 | 0.679 | 1.009 | 0.508 | 0.395 | 2.571 | 0.394 | 0.503 | 0.881 | 0.963 |
| lear_wx_clip | da | loss | 394,560 | 0.504 | 0.679 | 1.009 | 0.508 | 0.395 | 2.571 | 0.394 | 0.503 | 0.881 | 0.963 |
| lear_clip | da | loss | 394,560 | 0.507 | 0.683 | 1.016 | 0.513 | 0.397 | 2.592 | 0.397 | 0.503 | 0.881 | 0.964 |
| lear | da | loss | 394,560 | 0.510 | 0.687 | 1.020 | 0.513 | 0.400 | 2.594 | 0.399 | 0.504 | 0.881 | 0.964 |
| lear2_long_aci | da | loss | 394,560 | 0.522 | 0.703 | 1.066 | 0.508 | 0.403 | 2.786 | 0.403 | 0.497 | 0.900 | 0.972 |
| gbm_l1_v3_aci | da | loss | 394,560 | 0.531 | 0.715 | 1.106 | 0.500 | 0.416 | 2.697 | 0.409 | 0.498 | 0.900 | 0.973 |
| lear2_aci | da | loss | 394,560 | 0.530 | 0.714 | 1.099 | 0.508 | 0.406 | 2.890 | 0.412 | 0.497 | 0.899 | 0.972 |
| gbm_l1_aci | da | loss | 394,560 | 0.544 | 0.732 | 1.116 | 0.516 | 0.429 | 2.718 | 0.417 | 0.498 | 0.900 | 0.973 |
| gbm_l1_v3 | da | loss | 394,560 | 0.531 | 0.715 | 1.106 | 0.500 | 0.416 | 2.697 | 0.418 | 0.502 | 0.879 | 0.961 |
| lear2 | da | loss | 394,560 | 0.530 | 0.714 | 1.099 | 0.508 | 0.406 | 2.890 | 0.420 | 0.497 | 0.877 | 0.960 |
| gbm_l1 | da | loss | 394,560 | 0.544 | 0.732 | 1.116 | 0.516 | 0.429 | 2.718 | 0.426 | 0.500 | 0.880 | 0.961 |
| gbm_l2 | da | loss | 394,560 | 0.549 | 0.739 | 1.076 | 0.518 | 0.441 | 2.600 | 0.431 | 0.500 | 0.880 | 0.960 |
| persist_da_d1 | da | loss | 394,560 | 0.608 | 0.819 | 1.239 | 0.528 | 0.493 | 2.791 | 0.483 | 0.530 | 0.895 | 0.969 |
| lago_naive | da | loss | 394,560 | 0.743 | 1.000 | 1.605 | 0.594 | 0.603 | 3.393 | 0.597 | 0.528 | 0.894 | 0.969 |
| persist_rt_d2 | da | loss | 394,560 | 0.975 | 1.314 | 3.137 | 0.741 | 0.749 | 5.265 | 0.772 | 0.540 | 0.893 | 0.967 |
| weekly_da_d7 | da | loss | 394,560 | 0.989 | 1.331 | 2.053 | 0.703 | 0.797 | 4.626 | 0.799 | 0.534 | 0.890 | 0.967 |
| combo3_eq_aci | da | total | 394,560 | 5.589 | 0.521 | 11.888 | 0.124 | 4.160 | 32.725 | 4.432 | 0.499 | 0.901 | 0.969 |
| combo3wx_eq_aci | da | total | 394,560 | 5.638 | 0.526 | 11.824 | 0.124 | 4.222 | 32.547 | 4.475 | 0.499 | 0.900 | 0.969 |
| lear_clip_aci | da | total | 394,560 | 5.974 | 0.557 | 12.219 | 0.143 | 4.491 | 34.149 | 4.682 | 0.500 | 0.902 | 0.971 |
| lear_wx_clip_aci | da | total | 394,560 | 5.973 | 0.557 | 12.142 | 0.141 | 4.491 | 34.125 | 4.689 | 0.500 | 0.901 | 0.971 |
| lear_clip | da | total | 394,560 | 5.974 | 0.557 | 12.219 | 0.143 | 4.491 | 34.149 | 4.792 | 0.519 | 0.885 | 0.961 |
| lear_wx | da | total | 394,560 | 5.973 | 0.557 | 12.142 | 0.141 | 4.491 | 34.125 | 4.800 | 0.519 | 0.885 | 0.959 |
| lear_wx_clip | da | total | 394,560 | 5.973 | 0.557 | 12.142 | 0.141 | 4.491 | 34.125 | 4.800 | 0.519 | 0.885 | 0.959 |
| combo2_eq_aci | da | total | 394,560 | 6.025 | 0.562 | 13.329 | 0.130 | 4.335 | 38.144 | 4.837 | 0.498 | 0.900 | 0.968 |
| combo2_inv_aci | da | total | 394,560 | 6.030 | 0.563 | 13.346 | 0.130 | 4.336 | 38.222 | 4.843 | 0.498 | 0.900 | 0.968 |
| lear2_long_aci | da | total | 394,560 | 6.360 | 0.593 | 13.538 | 0.144 | 4.658 | 38.699 | 5.042 | 0.499 | 0.900 | 0.969 |
| lear | da | total | 394,560 | 6.300 | 0.588 | 12.721 | 0.167 | 4.804 | 34.725 | 5.047 | 0.521 | 0.885 | 0.961 |
| lear2_aci | da | total | 394,560 | 6.465 | 0.603 | 14.147 | 0.142 | 4.645 | 41.054 | 5.181 | 0.497 | 0.900 | 0.969 |
| assemble_v1e_v2c_aci | da | total | 394,560 | 6.526 | 0.609 | 13.894 | 0.150 | 4.769 | 39.902 | 5.182 | 0.501 | 0.902 | 0.972 |
| assemble_v1_final | da | total | 394,560 | 6.657 | 0.621 | 14.894 | 0.142 | 4.618 | 45.385 | 5.273 | 0.499 | 0.900 | 0.969 |
| lear2 | da | total | 394,560 | 6.465 | 0.603 | 14.147 | 0.142 | 4.645 | 41.054 | 5.299 | 0.512 | 0.880 | 0.959 |
| gbm_l2 | da | total | 394,560 | 6.692 | 0.624 | 13.419 | 0.149 | 5.188 | 35.265 | 5.439 | 0.506 | 0.875 | 0.953 |
| gbm_l1_aci | da | total | 394,560 | 6.816 | 0.636 | 14.522 | 0.147 | 5.066 | 40.069 | 5.449 | 0.499 | 0.900 | 0.969 |
| gbm_l1_v3_aci | da | total | 394,560 | 6.939 | 0.647 | 14.322 | 0.149 | 5.285 | 38.360 | 5.536 | 0.498 | 0.900 | 0.968 |
| gbm_l1 | da | total | 394,560 | 6.816 | 0.636 | 14.522 | 0.147 | 5.066 | 40.069 | 5.604 | 0.504 | 0.875 | 0.954 |
| gbm_l1_v3 | da | total | 394,560 | 6.939 | 0.647 | 14.322 | 0.149 | 5.285 | 38.360 | 5.736 | 0.496 | 0.869 | 0.950 |
| persist_da_d1 | da | total | 394,560 | 7.968 | 0.744 | 17.422 | 0.169 | 6.237 | 40.865 | 6.512 | 0.527 | 0.896 | 0.968 |
| lago_naive | da | total | 394,560 | 10.717 | 1.000 | 25.416 | 0.212 | 8.392 | 54.894 | 8.979 | 0.526 | 0.895 | 0.970 |
| persist_rt_d2 | da | total | 394,560 | 15.912 | 1.485 | 51.218 | 0.314 | 12.266 | 85.191 | 13.075 | 0.527 | 0.892 | 0.968 |
| weekly_da_d7 | da | total | 394,560 | 15.697 | 1.465 | 33.542 | 0.293 | 12.219 | 81.773 | 13.091 | 0.524 | 0.888 | 0.968 |
| assemble_v1_final | rt | congestion | 394,517 | 5.837 | 0.862 | 28.484 | 1.761 | 2.639 | 66.578 | 4.814 | 0.505 | 0.903 | 0.974 |
| lear2_long_aci | rt | congestion | 394,517 | 5.837 | 0.862 | 28.484 | 1.761 | 2.639 | 66.578 | 4.814 | 0.505 | 0.903 | 0.974 |
| zero_congestion | rt | congestion | 394,517 | 5.400 | 0.798 | 29.922 | 2.000 | 1.594 | 77.680 | 4.863 | 0.770 | 0.909 | 0.970 |
| struct_cong | rt | congestion | 394,517 | 5.392 | 0.797 | 29.010 | 1.794 | 1.929 | 71.151 | 4.919 | 0.699 | 0.900 | 0.964 |
| struct_cong_out | rt | congestion | 394,517 | 5.428 | 0.802 | 28.986 | 1.796 | 1.999 | 70.536 | 4.971 | 0.702 | 0.898 | 0.962 |
| combo2_inv_aci | rt | congestion | 394,517 | 6.044 | 0.893 | 28.073 | 1.756 | 3.089 | 62.156 | 5.008 | 0.507 | 0.903 | 0.973 |
| assemble_v1e_v2c_aci | rt | congestion | 394,517 | 6.027 | 0.890 | 28.532 | 1.759 | 2.895 | 65.509 | 5.017 | 0.506 | 0.903 | 0.973 |
| lear2_aci | rt | congestion | 394,517 | 6.027 | 0.890 | 28.532 | 1.759 | 2.895 | 65.509 | 5.017 | 0.506 | 0.903 | 0.973 |
| combo2_eq_aci | rt | congestion | 394,517 | 6.055 | 0.894 | 28.073 | 1.756 | 3.105 | 62.083 | 5.018 | 0.507 | 0.903 | 0.973 |
| lear_wx_clip_aci | rt | congestion | 394,517 | 6.050 | 0.894 | 28.399 | 1.764 | 2.949 | 64.945 | 5.065 | 0.502 | 0.903 | 0.975 |
| combo3wx_eq_aci | rt | congestion | 394,517 | 6.099 | 0.901 | 27.851 | 1.749 | 3.254 | 60.142 | 5.072 | 0.503 | 0.903 | 0.973 |
| combo3_eq_aci | rt | congestion | 394,517 | 6.089 | 0.899 | 28.368 | 1.759 | 3.135 | 62.190 | 5.085 | 0.504 | 0.903 | 0.973 |
| lear_clip_aci | rt | congestion | 394,517 | 6.157 | 0.910 | 29.672 | 1.764 | 3.028 | 65.574 | 5.170 | 0.502 | 0.903 | 0.975 |
| lear2 | rt | congestion | 394,517 | 6.027 | 0.890 | 28.532 | 1.759 | 2.895 | 65.509 | 5.211 | 0.534 | 0.887 | 0.963 |
| lear_wx | rt | congestion | 394,517 | 6.050 | 0.894 | 28.399 | 1.764 | 2.949 | 64.945 | 5.239 | 0.525 | 0.892 | 0.968 |
| lear_wx_clip | rt | congestion | 394,517 | 6.050 | 0.894 | 28.399 | 1.764 | 2.949 | 64.945 | 5.239 | 0.525 | 0.892 | 0.968 |
| lear_clip | rt | congestion | 394,517 | 6.157 | 0.910 | 29.672 | 1.764 | 3.028 | 65.574 | 5.346 | 0.526 | 0.892 | 0.968 |
| gbm_l1_aci | rt | congestion | 394,517 | 6.413 | 0.947 | 28.319 | 1.788 | 3.580 | 60.209 | 5.391 | 0.507 | 0.902 | 0.972 |
| gbm_l1_v3_aci | rt | congestion | 394,517 | 6.591 | 0.974 | 28.114 | 1.770 | 3.919 | 57.345 | 5.493 | 0.506 | 0.902 | 0.972 |
| persist_da_d1 | rt | congestion | 394,517 | 6.238 | 0.921 | 28.327 | 1.626 | 3.613 | 56.078 | 5.561 | 0.664 | 0.912 | 0.975 |
| gbm_l1 | rt | congestion | 394,517 | 6.413 | 0.947 | 28.319 | 1.788 | 3.580 | 60.209 | 5.618 | 0.531 | 0.891 | 0.964 |
| gbm_l1_v3 | rt | congestion | 394,517 | 6.591 | 0.974 | 28.114 | 1.770 | 3.919 | 57.345 | 5.760 | 0.536 | 0.888 | 0.960 |
| lago_naive | rt | congestion | 394,517 | 6.769 | 1.000 | 29.253 | 1.658 | 3.991 | 59.540 | 6.030 | 0.663 | 0.912 | 0.976 |
| lear | rt | congestion | 394,517 | 6.909 | 1.021 | 280.312 | 1.764 | 3.613 | 69.499 | 6.118 | 0.526 | 0.892 | 0.968 |
| struct_cong_l2 | rt | congestion | 394,517 | 7.287 | 1.076 | 29.066 | 1.749 | 4.561 | 59.050 | 6.156 | 0.521 | 0.882 | 0.960 |
| weekly_da_d7 | rt | congestion | 394,517 | 7.358 | 1.087 | 30.170 | 1.708 | 4.408 | 63.374 | 6.511 | 0.660 | 0.913 | 0.976 |
| gbm_l2 | rt | congestion | 394,517 | 8.398 | 1.241 | 29.210 | 1.747 | 5.950 | 54.883 | 6.905 | 0.528 | 0.887 | 0.959 |
| persist_rt_d2 | rt | congestion | 394,517 | 7.835 | 1.157 | 38.570 | 1.708 | 4.618 | 68.926 | 7.208 | 0.653 | 0.914 | 0.976 |
| combo3wx_eq_aci | rt | energy | 394,517 | 12.341 | 0.810 | 42.911 | 0.322 | 8.208 | 90.800 | 9.908 | 0.500 | 0.902 | 0.974 |
| assemble_v1_final | rt | energy | 394,517 | 12.561 | 0.824 | 43.261 | 0.326 | 8.313 | 93.200 | 10.096 | 0.500 | 0.901 | 0.974 |
| combo3_eq_aci | rt | energy | 394,517 | 12.561 | 0.824 | 43.261 | 0.326 | 8.313 | 93.200 | 10.096 | 0.500 | 0.901 | 0.974 |
| lear_wx_clip_aci | rt | energy | 394,517 | 12.659 | 0.831 | 42.925 | 0.335 | 8.519 | 91.243 | 10.192 | 0.500 | 0.901 | 0.974 |
| assemble_v1e_v2c_aci | rt | energy | 394,517 | 12.683 | 0.832 | 43.115 | 0.339 | 8.562 | 90.905 | 10.197 | 0.501 | 0.901 | 0.974 |
| lear_clip_aci | rt | energy | 394,517 | 12.683 | 0.832 | 43.115 | 0.339 | 8.562 | 90.905 | 10.197 | 0.501 | 0.901 | 0.974 |
| combo2_eq_aci | rt | energy | 394,517 | 12.717 | 0.835 | 43.459 | 0.329 | 8.464 | 93.449 | 10.237 | 0.499 | 0.902 | 0.973 |
| combo2_inv_aci | rt | energy | 394,517 | 12.717 | 0.835 | 43.449 | 0.329 | 8.465 | 93.423 | 10.238 | 0.499 | 0.902 | 0.973 |
| lear2_long_aci | rt | energy | 394,517 | 12.842 | 0.843 | 43.433 | 0.336 | 8.561 | 94.110 | 10.314 | 0.500 | 0.901 | 0.974 |
| gbm_l1_v3_aci | rt | energy | 394,517 | 13.085 | 0.859 | 43.649 | 0.345 | 8.902 | 92.491 | 10.396 | 0.498 | 0.901 | 0.974 |
| lear_wx_clip | rt | energy | 394,517 | 12.659 | 0.831 | 42.925 | 0.335 | 8.519 | 91.243 | 10.418 | 0.527 | 0.886 | 0.966 |
| lear_wx | rt | energy | 394,517 | 12.659 | 0.831 | 42.925 | 0.335 | 8.519 | 91.243 | 10.418 | 0.527 | 0.886 | 0.966 |
| lear2_aci | rt | energy | 394,517 | 12.964 | 0.851 | 43.416 | 0.341 | 8.848 | 91.109 | 10.418 | 0.500 | 0.902 | 0.974 |
| lear | rt | energy | 394,517 | 12.683 | 0.832 | 43.115 | 0.339 | 8.562 | 90.905 | 10.420 | 0.527 | 0.887 | 0.967 |
| lear_clip | rt | energy | 394,517 | 12.683 | 0.832 | 43.115 | 0.339 | 8.562 | 90.905 | 10.420 | 0.527 | 0.887 | 0.967 |
| gbm_l1_aci | rt | energy | 394,517 | 13.492 | 0.885 | 44.208 | 0.353 | 9.095 | 96.976 | 10.737 | 0.499 | 0.901 | 0.973 |
| lear2 | rt | energy | 394,517 | 12.964 | 0.851 | 43.416 | 0.341 | 8.848 | 91.109 | 10.740 | 0.522 | 0.882 | 0.965 |
| gbm_l1_v3 | rt | energy | 394,517 | 13.085 | 0.859 | 43.649 | 0.345 | 8.902 | 92.491 | 10.768 | 0.526 | 0.881 | 0.960 |
| gbm_l1 | rt | energy | 394,517 | 13.492 | 0.885 | 44.208 | 0.353 | 9.095 | 96.976 | 11.082 | 0.519 | 0.881 | 0.958 |
| persist_da_d1 | rt | energy | 394,517 | 13.659 | 0.896 | 43.681 | 0.349 | 10.202 | 79.293 | 11.217 | 0.532 | 0.896 | 0.967 |
| gbm_l2 | rt | energy | 394,517 | 14.875 | 0.976 | 44.038 | 0.396 | 11.013 | 88.201 | 12.186 | 0.527 | 0.881 | 0.959 |
| lago_naive | rt | energy | 394,517 | 15.237 | 1.000 | 46.094 | 0.378 | 11.526 | 85.696 | 12.545 | 0.532 | 0.896 | 0.967 |
| weekly_da_d7 | rt | energy | 394,517 | 17.499 | 1.148 | 48.824 | 0.426 | 13.317 | 96.884 | 14.334 | 0.533 | 0.893 | 0.965 |
| persist_rt_d2 | rt | energy | 394,517 | 18.066 | 1.186 | 59.021 | 0.443 | 13.804 | 98.982 | 15.033 | 0.535 | 0.900 | 0.968 |
| combo3wx_eq_aci | rt | loss | 394,517 | 0.734 | 0.734 | 3.059 | 0.624 | 0.482 | 5.525 | 0.593 | 0.502 | 0.902 | 0.974 |
| assemble_v1_final | rt | loss | 394,517 | 0.741 | 0.741 | 3.073 | 0.633 | 0.486 | 5.593 | 0.600 | 0.502 | 0.902 | 0.974 |
| combo3_eq_aci | rt | loss | 394,517 | 0.741 | 0.741 | 3.073 | 0.633 | 0.486 | 5.593 | 0.600 | 0.502 | 0.902 | 0.974 |
| lear_wx_clip_aci | rt | loss | 394,517 | 0.759 | 0.759 | 3.056 | 0.649 | 0.507 | 5.546 | 0.609 | 0.501 | 0.902 | 0.974 |
| combo2_eq_aci | rt | loss | 394,517 | 0.754 | 0.754 | 3.097 | 0.640 | 0.496 | 5.664 | 0.610 | 0.502 | 0.902 | 0.974 |
| combo2_inv_aci | rt | loss | 394,517 | 0.755 | 0.754 | 3.097 | 0.640 | 0.496 | 5.664 | 0.610 | 0.502 | 0.902 | 0.974 |
| assemble_v1e_v2c_aci | rt | loss | 394,517 | 0.761 | 0.761 | 3.070 | 0.652 | 0.508 | 5.569 | 0.612 | 0.501 | 0.902 | 0.974 |
| lear_clip_aci | rt | loss | 394,517 | 0.761 | 0.761 | 3.070 | 0.652 | 0.508 | 5.569 | 0.612 | 0.501 | 0.902 | 0.974 |
| lear2_long_aci | rt | loss | 394,517 | 0.781 | 0.780 | 3.101 | 0.659 | 0.520 | 5.733 | 0.621 | 0.501 | 0.901 | 0.973 |
| lear_wx | rt | loss | 394,517 | 0.759 | 0.759 | 3.056 | 0.649 | 0.507 | 5.546 | 0.622 | 0.512 | 0.879 | 0.963 |
| lear_wx_clip | rt | loss | 394,517 | 0.759 | 0.759 | 3.056 | 0.649 | 0.507 | 5.546 | 0.622 | 0.512 | 0.879 | 0.963 |
| lear_clip | rt | loss | 394,517 | 0.761 | 0.761 | 3.070 | 0.652 | 0.508 | 5.569 | 0.624 | 0.512 | 0.880 | 0.963 |
| lear | rt | loss | 394,517 | 0.761 | 0.761 | 3.070 | 0.652 | 0.508 | 5.568 | 0.624 | 0.512 | 0.880 | 0.963 |
| gbm_l1_v3_aci | rt | loss | 394,517 | 0.777 | 0.777 | 3.108 | 0.654 | 0.519 | 5.692 | 0.627 | 0.502 | 0.902 | 0.973 |
| lear2_aci | rt | loss | 394,517 | 0.782 | 0.781 | 3.116 | 0.659 | 0.524 | 5.680 | 0.628 | 0.501 | 0.902 | 0.973 |
| gbm_l1_aci | rt | loss | 394,517 | 0.785 | 0.784 | 3.118 | 0.667 | 0.521 | 5.796 | 0.634 | 0.502 | 0.902 | 0.973 |
| lear2 | rt | loss | 394,517 | 0.782 | 0.781 | 3.116 | 0.659 | 0.524 | 5.680 | 0.642 | 0.511 | 0.876 | 0.961 |
| gbm_l1_v3 | rt | loss | 394,517 | 0.777 | 0.777 | 3.108 | 0.654 | 0.519 | 5.692 | 0.647 | 0.515 | 0.876 | 0.959 |
| gbm_l1 | rt | loss | 394,517 | 0.785 | 0.784 | 3.118 | 0.667 | 0.521 | 5.796 | 0.649 | 0.510 | 0.876 | 0.958 |
| persist_da_d1 | rt | loss | 394,517 | 0.895 | 0.894 | 3.098 | 0.695 | 0.679 | 4.987 | 0.705 | 0.540 | 0.894 | 0.968 |
| gbm_l2 | rt | loss | 394,517 | 0.865 | 0.865 | 3.124 | 0.682 | 0.620 | 5.514 | 0.717 | 0.502 | 0.871 | 0.957 |
| lago_naive | rt | loss | 394,517 | 1.001 | 1.000 | 3.273 | 0.741 | 0.765 | 5.481 | 0.794 | 0.538 | 0.893 | 0.968 |
| persist_rt_d2 | rt | loss | 394,517 | 1.067 | 1.066 | 4.234 | 0.756 | 0.780 | 6.516 | 0.894 | 0.549 | 0.896 | 0.968 |
| weekly_da_d7 | rt | loss | 394,517 | 1.157 | 1.156 | 3.503 | 0.815 | 0.892 | 6.178 | 0.924 | 0.541 | 0.890 | 0.967 |
| combo3wx_eq_aci | rt | total | 394,517 | 13.068 | 0.770 | 49.637 | 0.271 | 8.601 | 97.939 | 10.736 | 0.500 | 0.901 | 0.972 |
| combo3_eq_aci | rt | total | 394,517 | 13.072 | 0.770 | 50.195 | 0.272 | 8.482 | 100.273 | 10.754 | 0.500 | 0.901 | 0.973 |
| combo2_inv_aci | rt | total | 394,517 | 13.256 | 0.781 | 50.534 | 0.274 | 8.635 | 101.058 | 10.890 | 0.500 | 0.901 | 0.972 |
| combo2_eq_aci | rt | total | 394,517 | 13.258 | 0.781 | 50.534 | 0.274 | 8.635 | 101.094 | 10.891 | 0.500 | 0.901 | 0.972 |
| lear_wx_clip_aci | rt | total | 394,517 | 13.739 | 0.809 | 50.214 | 0.295 | 8.989 | 104.000 | 11.188 | 0.499 | 0.900 | 0.973 |
| lear_clip_aci | rt | total | 394,517 | 13.765 | 0.811 | 50.610 | 0.297 | 8.993 | 104.428 | 11.228 | 0.500 | 0.900 | 0.973 |
| gbm_l1_aci | rt | total | 394,517 | 13.650 | 0.804 | 50.719 | 0.281 | 9.029 | 101.441 | 11.232 | 0.500 | 0.902 | 0.972 |
| gbm_l1_v3_aci | rt | total | 394,517 | 13.682 | 0.806 | 50.044 | 0.281 | 9.270 | 97.516 | 11.280 | 0.499 | 0.902 | 0.972 |
| lear2_long_aci | rt | total | 394,517 | 13.964 | 0.823 | 51.281 | 0.293 | 9.034 | 107.621 | 11.303 | 0.499 | 0.900 | 0.972 |
| assemble_v1_final | rt | total | 394,517 | 13.760 | 0.811 | 52.060 | 0.282 | 8.388 | 115.826 | 11.329 | 0.499 | 0.901 | 0.972 |
| lear_wx | rt | total | 394,517 | 13.739 | 0.809 | 50.214 | 0.295 | 8.989 | 104.000 | 11.383 | 0.516 | 0.882 | 0.964 |
| lear_wx_clip | rt | total | 394,517 | 13.739 | 0.809 | 50.214 | 0.295 | 8.989 | 104.000 | 11.383 | 0.516 | 0.882 | 0.964 |
| lear_clip | rt | total | 394,517 | 13.765 | 0.811 | 50.610 | 0.297 | 8.993 | 104.428 | 11.413 | 0.516 | 0.882 | 0.964 |
| gbm_l1 | rt | total | 394,517 | 13.650 | 0.804 | 50.719 | 0.281 | 9.029 | 101.441 | 11.441 | 0.511 | 0.876 | 0.959 |
| lear2_aci | rt | total | 394,517 | 14.101 | 0.831 | 51.187 | 0.296 | 9.286 | 105.591 | 11.476 | 0.499 | 0.901 | 0.972 |
| lear | rt | total | 394,517 | 13.841 | 0.815 | 50.650 | 0.303 | 9.072 | 104.448 | 11.477 | 0.517 | 0.882 | 0.964 |
| gbm_l1_v3 | rt | total | 394,517 | 13.682 | 0.806 | 50.044 | 0.281 | 9.270 | 97.516 | 11.492 | 0.514 | 0.873 | 0.957 |
| assemble_v1e_v2c_aci | rt | total | 394,517 | 14.053 | 0.828 | 51.631 | 0.299 | 8.919 | 111.582 | 11.519 | 0.500 | 0.900 | 0.973 |
| lear2 | rt | total | 394,517 | 14.101 | 0.831 | 51.187 | 0.296 | 9.286 | 105.591 | 11.683 | 0.511 | 0.877 | 0.960 |
| persist_da_d1 | rt | total | 394,517 | 14.838 | 0.874 | 51.088 | 0.297 | 10.630 | 94.783 | 12.161 | 0.526 | 0.893 | 0.968 |
| gbm_l2 | rt | total | 394,517 | 16.099 | 0.948 | 52.470 | 0.310 | 11.805 | 97.686 | 13.465 | 0.501 | 0.873 | 0.955 |
| lago_naive | rt | total | 394,517 | 16.975 | 1.000 | 54.210 | 0.328 | 12.368 | 104.497 | 14.027 | 0.524 | 0.892 | 0.968 |
| weekly_da_d7 | rt | total | 394,517 | 19.882 | 1.171 | 58.222 | 0.377 | 14.693 | 118.468 | 16.446 | 0.524 | 0.889 | 0.967 |
| persist_rt_d2 | rt | total | 394,517 | 19.952 | 1.175 | 70.502 | 0.379 | 14.566 | 122.283 | 16.774 | 0.528 | 0.894 | 0.968 |

## Diebold–Mariano vs yesterday's DA price (daily-averaged loss, HAC)

One-sided p-values for H1: the model's loss is lower than `persist_da_d1`'s, for CRPS, squared error (se) and absolute error (ae). Smaller = stronger evidence. Reported, not thresholded. Days where any compared model lacks quantiles are dropped from the CRPS test.

| component | market | model | p_crps | p_se | p_ae |
|---|---|---|---|---|---|
| congestion | da | combo3wx_eq_aci | 0.000 | 0.000 | 0.146 |
| congestion | da | assemble_v1_final | 0.000 | 0.002 | 0.288 |
| congestion | da | lear2_long_aci | 0.000 | 0.002 | 0.288 |
| congestion | da | combo3_eq_aci | 0.000 | 0.001 | 0.215 |
| congestion | da | combo2_inv_aci | 0.000 | 0.001 | 0.428 |
| congestion | da | assemble_v1e_v2c_aci | 0.000 | 0.004 | 0.284 |
| congestion | da | lear2_aci | 0.000 | 0.004 | 0.284 |
| congestion | da | lear_wx_clip_aci | 0.000 | 0.003 | 0.306 |
| congestion | da | combo2_eq_aci | 0.000 | 0.001 | 0.472 |
| congestion | da | lear_clip_aci | 0.001 | 0.019 | 0.581 |
| congestion | da | lear2 | 0.005 | 0.004 | 0.284 |
| congestion | da | lear_wx | 0.006 | 0.003 | 0.306 |
| congestion | da | lear_wx_clip | 0.006 | 0.003 | 0.306 |
| congestion | da | lear_clip | 0.043 | 0.019 | 0.581 |
| congestion | da | struct_cong | 0.247 | 0.514 | 0.132 |
| congestion | da | gbm_l1_v3_aci | 0.381 | 0.013 | 0.997 |
| congestion | da | gbm_l1_aci | 0.436 | 0.040 | 0.991 |
| congestion | da | lear | 0.475 | 0.848 | 0.951 |
| congestion | da | struct_cong_out | 0.476 | 0.755 | 0.335 |
| congestion | da | gbm_l1 | 0.901 | 0.040 | 0.991 |
| congestion | da | gbm_l1_v3 | 0.925 | 0.013 | 0.997 |
| congestion | da | struct_cong_l2 | 0.988 | 0.158 | 1.000 |
| congestion | da | zero_congestion | 0.997 | 0.999 | 0.999 |
| congestion | da | gbm_l2 | 0.999 | 0.448 | 1.000 |
| congestion | da | lago_naive | 1.000 | 0.999 | 1.000 |
| congestion | da | weekly_da_d7 | 1.000 | 1.000 | 1.000 |
| congestion | da | persist_rt_d2 | 1.000 | 0.998 | 1.000 |
| congestion | rt | assemble_v1_final | 0.000 | 0.658 | 0.007 |
| congestion | rt | lear2_long_aci | 0.000 | 0.658 | 0.007 |
| congestion | rt | combo2_inv_aci | 0.000 | 0.223 | 0.096 |
| congestion | rt | combo2_eq_aci | 0.000 | 0.223 | 0.114 |
| congestion | rt | combo3wx_eq_aci | 0.000 | 0.071 | 0.139 |
| congestion | rt | struct_cong | 0.000 | 0.916 | 0.000 |
| congestion | rt | combo3_eq_aci | 0.000 | 0.549 | 0.163 |
| congestion | rt | assemble_v1e_v2c_aci | 0.000 | 0.717 | 0.088 |
| congestion | rt | lear2_aci | 0.000 | 0.717 | 0.088 |
| congestion | rt | lear_wx_clip_aci | 0.000 | 0.584 | 0.100 |
| congestion | rt | zero_congestion | 0.000 | 0.986 | 0.000 |
| congestion | rt | struct_cong_out | 0.000 | 0.911 | 0.000 |
| congestion | rt | lear_clip_aci | 0.002 | 0.966 | 0.285 |
| congestion | rt | lear2 | 0.012 | 0.717 | 0.088 |
| congestion | rt | lear_wx | 0.013 | 0.584 | 0.100 |
| congestion | rt | lear_wx_clip | 0.013 | 0.584 | 0.100 |
| congestion | rt | lear_clip | 0.089 | 0.966 | 0.285 |
| congestion | rt | gbm_l1_aci | 0.262 | 0.491 | 0.786 |
| congestion | rt | gbm_l1_v3_aci | 0.516 | 0.259 | 0.974 |
| congestion | rt | gbm_l1 | 0.768 | 0.491 | 0.786 |
| congestion | rt | lear | 0.871 | 0.855 | 0.889 |
| congestion | rt | gbm_l1_v3 | 0.956 | 0.259 | 0.974 |
| congestion | rt | struct_cong_l2 | 1.000 | 0.973 | 1.000 |
| congestion | rt | lago_naive | 1.000 | 0.995 | 0.999 |
| congestion | rt | weekly_da_d7 | 1.000 | 1.000 | 1.000 |
| congestion | rt | gbm_l2 | 1.000 | 0.917 | 1.000 |
| congestion | rt | persist_rt_d2 | 1.000 | 0.999 | 1.000 |
| total | da | combo3_eq_aci | 0.000 | 0.000 | 0.000 |
| total | da | combo3wx_eq_aci | 0.000 | 0.000 | 0.000 |
| total | da | combo2_eq_aci | 0.000 | 0.001 | 0.000 |
| total | da | combo2_inv_aci | 0.000 | 0.001 | 0.000 |
| total | da | lear_clip_aci | 0.000 | 0.000 | 0.000 |
| total | da | lear_clip | 0.000 | 0.000 | 0.000 |
| total | da | lear_wx_clip_aci | 0.000 | 0.000 | 0.000 |
| total | da | lear_wx | 0.000 | 0.000 | 0.000 |
| total | da | lear_wx_clip | 0.000 | 0.000 | 0.000 |
| total | da | lear2_long_aci | 0.000 | 0.001 | 0.000 |
| total | da | assemble_v1_final | 0.000 | 0.006 | 0.000 |
| total | da | assemble_v1e_v2c_aci | 0.000 | 0.001 | 0.000 |
| total | da | lear2_aci | 0.000 | 0.004 | 0.000 |
| total | da | lear | 0.000 | 0.001 | 0.000 |
| total | da | lear2 | 0.000 | 0.004 | 0.000 |
| total | da | gbm_l1_aci | 0.000 | 0.011 | 0.000 |
| total | da | gbm_l2 | 0.000 | 0.001 | 0.000 |
| total | da | gbm_l1 | 0.000 | 0.011 | 0.000 |
| total | da | gbm_l1_v3_aci | 0.000 | 0.013 | 0.001 |
| total | da | gbm_l1_v3 | 0.004 | 0.013 | 0.001 |
| total | da | lago_naive | 1.000 | 0.993 | 1.000 |
| total | da | weekly_da_d7 | 1.000 | 1.000 | 1.000 |
| total | da | persist_rt_d2 | 1.000 | 0.993 | 1.000 |
| total | rt | combo3_eq_aci | 0.000 | 0.175 | 0.000 |
| total | rt | combo3wx_eq_aci | 0.000 | 0.122 | 0.000 |
| total | rt | combo2_inv_aci | 0.000 | 0.294 | 0.000 |
| total | rt | combo2_eq_aci | 0.000 | 0.294 | 0.000 |
| total | rt | gbm_l1_aci | 0.001 | 0.348 | 0.002 |
| total | rt | lear_wx_clip_aci | 0.002 | 0.218 | 0.004 |
| total | rt | lear_clip_aci | 0.002 | 0.315 | 0.004 |
| total | rt | lear2_long_aci | 0.002 | 0.571 | 0.012 |
| total | rt | gbm_l1_v3_aci | 0.002 | 0.215 | 0.002 |
| total | rt | assemble_v1_final | 0.006 | 0.804 | 0.011 |
| total | rt | lear_clip | 0.009 | 0.315 | 0.004 |
| total | rt | lear_wx | 0.009 | 0.218 | 0.004 |
| total | rt | lear_wx_clip | 0.009 | 0.218 | 0.004 |
| total | rt | assemble_v1e_v2c_aci | 0.009 | 0.706 | 0.017 |
| total | rt | lear2_aci | 0.011 | 0.535 | 0.025 |
| total | rt | gbm_l1 | 0.011 | 0.348 | 0.002 |
| total | rt | lear | 0.015 | 0.330 | 0.007 |
| total | rt | gbm_l1_v3 | 0.016 | 0.215 | 0.002 |
| total | rt | lear2 | 0.045 | 0.535 | 0.025 |
| total | rt | gbm_l2 | 0.983 | 0.771 | 0.979 |
| total | rt | lago_naive | 1.000 | 0.993 | 1.000 |
| total | rt | weekly_da_d7 | 1.000 | 1.000 | 1.000 |
| total | rt | persist_rt_d2 | 1.000 | 0.990 | 1.000 |

## Fold stability (total price)

| model | market | folds | frac_folds_beat_ref | median_fold_rmae |
|---|---|---|---|---|
| combo3_eq_aci | da | 36 | 0.972 | 0.593 |
| combo2_eq_aci | da | 36 | 0.972 | 0.597 |
| combo2_inv_aci | da | 36 | 0.972 | 0.597 |
| combo3wx_eq_aci | da | 36 | 0.917 | 0.609 |
| lear_wx | da | 36 | 0.944 | 0.631 |
| lear_wx_clip_aci | da | 36 | 0.944 | 0.631 |
| lear_wx_clip | da | 36 | 0.944 | 0.631 |
| lear_clip | da | 36 | 0.944 | 0.637 |
| lear_clip_aci | da | 36 | 0.944 | 0.637 |
| lear | da | 36 | 0.889 | 0.638 |
| lear2_aci | da | 36 | 0.944 | 0.663 |
| lear2 | da | 36 | 0.944 | 0.663 |
| assemble_v1e_v2c_aci | da | 36 | 0.917 | 0.667 |
| assemble_v1_final | da | 36 | 0.889 | 0.673 |
| gbm_l1_aci | da | 36 | 0.917 | 0.676 |
| gbm_l1 | da | 36 | 0.917 | 0.676 |
| gbm_l1_v3_aci | da | 36 | 0.944 | 0.708 |
| gbm_l1_v3 | da | 36 | 0.944 | 0.708 |
| gbm_l2 | da | 36 | 0.861 | 0.710 |
| lear2_long_aci | da | 36 | 0.917 | 0.713 |
| persist_da_d1 | da | 36 | 0.833 | 0.842 |
| lago_naive | da | 36 | 0.000 | 1.000 |
| weekly_da_d7 | da | 36 | 0.000 | 1.364 |
| persist_rt_d2 | da | 36 | 0.056 | 1.666 |
| combo3_eq_aci | rt | 36 | 0.944 | 0.823 |
| combo3wx_eq_aci | rt | 36 | 0.917 | 0.825 |
| combo2_eq_aci | rt | 36 | 0.944 | 0.842 |
| combo2_inv_aci | rt | 36 | 0.944 | 0.842 |
| assemble_v1_final | rt | 36 | 0.944 | 0.852 |
| gbm_l1_v3_aci | rt | 36 | 0.944 | 0.858 |
| gbm_l1_v3 | rt | 36 | 0.944 | 0.858 |
| assemble_v1e_v2c_aci | rt | 36 | 0.861 | 0.864 |
| lear | rt | 36 | 0.889 | 0.866 |
| lear_clip | rt | 36 | 0.889 | 0.866 |
| lear_clip_aci | rt | 36 | 0.889 | 0.866 |
| lear_wx_clip_aci | rt | 36 | 0.861 | 0.872 |
| lear_wx | rt | 36 | 0.861 | 0.872 |
| lear_wx_clip | rt | 36 | 0.861 | 0.872 |
| lear2_long_aci | rt | 36 | 0.861 | 0.880 |
| gbm_l1 | rt | 36 | 0.972 | 0.880 |
| gbm_l1_aci | rt | 36 | 0.972 | 0.880 |
| lear2 | rt | 36 | 0.833 | 0.892 |
| lear2_aci | rt | 36 | 0.833 | 0.892 |
| gbm_l2 | rt | 36 | 0.694 | 0.934 |
| persist_da_d1 | rt | 36 | 0.806 | 0.934 |
| lago_naive | rt | 36 | 0.000 | 1.000 |
| weekly_da_d7 | rt | 36 | 0.111 | 1.111 |
| persist_rt_d2 | rt | 36 | 0.111 | 1.231 |

## Interval calibration tests (total price)

miss90 / miss98: share of outcomes outside the 90% / 98% intervals (nominal 0.10 / 0.02). Kupiec p: H0 miss rate = nominal (pooled misses are dependent across zones and hours, so p is optimistic). Christoffersen p: median over zone × hour day-sequences of the independence test (H0: misses do not cluster in time). Descriptive only.

| model | market | miss90 | kupiec_p90 | miss98 | kupiec_p98 | christoffersen_p90_median |
|---|---|---|---|---|---|---|
| assemble_v1_final | da | 0.100 | 0.817 | 0.031 | 0.000 | 0.000 |
| assemble_v1_final | rt | 0.099 | 0.294 | 0.028 | 0.000 | 0.000 |
| assemble_v1e_v2c_aci | da | 0.098 | 0.000 | 0.028 | 0.000 | 0.000 |
| assemble_v1e_v2c_aci | rt | 0.100 | 0.330 | 0.027 | 0.000 | 0.000 |
| combo2_eq_aci | da | 0.100 | 0.632 | 0.032 | 0.000 | 0.000 |
| combo2_eq_aci | rt | 0.099 | 0.020 | 0.028 | 0.000 | 0.000 |
| combo2_inv_aci | da | 0.100 | 0.686 | 0.032 | 0.000 | 0.000 |
| combo2_inv_aci | rt | 0.099 | 0.020 | 0.028 | 0.000 | 0.000 |
| combo3_eq_aci | da | 0.099 | 0.286 | 0.031 | 0.000 | 0.000 |
| combo3_eq_aci | rt | 0.099 | 0.034 | 0.027 | 0.000 | 0.000 |
| combo3wx_eq_aci | da | 0.100 | 0.706 | 0.031 | 0.000 | 0.000 |
| combo3wx_eq_aci | rt | 0.099 | 0.041 | 0.028 | 0.000 | 0.000 |
| gbm_l1 | da | 0.125 | 0.000 | 0.046 | 0.000 | 0.000 |
| gbm_l1 | rt | 0.124 | 0.000 | 0.041 | 0.000 | 0.000 |
| gbm_l1_aci | da | 0.100 | 0.991 | 0.031 | 0.000 | 0.000 |
| gbm_l1_aci | rt | 0.098 | 0.000 | 0.028 | 0.000 | 0.000 |
| gbm_l1_v3 | da | 0.131 | 0.000 | 0.050 | 0.000 | 0.000 |
| gbm_l1_v3 | rt | 0.127 | 0.000 | 0.043 | 0.000 | 0.000 |
| gbm_l1_v3_aci | da | 0.100 | 0.940 | 0.032 | 0.000 | 0.000 |
| gbm_l1_v3_aci | rt | 0.098 | 0.000 | 0.028 | 0.000 | 0.000 |
| gbm_l2 | da | 0.125 | 0.000 | 0.047 | 0.000 | 0.000 |
| gbm_l2 | rt | 0.127 | 0.000 | 0.045 | 0.000 | 0.000 |
| lago_naive | da | 0.105 | 0.000 | 0.030 | 0.000 | 0.000 |
| lago_naive | rt | 0.108 | 0.000 | 0.032 | 0.000 | 0.000 |
| lear | da | 0.115 | 0.000 | 0.039 | 0.000 | 0.000 |
| lear | rt | 0.118 | 0.000 | 0.036 | 0.000 | 0.000 |
| lear2 | da | 0.120 | 0.000 | 0.041 | 0.000 | 0.000 |
| lear2 | rt | 0.123 | 0.000 | 0.040 | 0.000 | 0.000 |
| lear2_aci | da | 0.100 | 0.366 | 0.031 | 0.000 | 0.000 |
| lear2_aci | rt | 0.099 | 0.154 | 0.028 | 0.000 | 0.000 |
| lear2_long_aci | da | 0.100 | 0.901 | 0.031 | 0.000 | 0.000 |
| lear2_long_aci | rt | 0.100 | 0.791 | 0.028 | 0.000 | 0.000 |
| lear_clip | da | 0.115 | 0.000 | 0.039 | 0.000 | 0.000 |
| lear_clip | rt | 0.118 | 0.000 | 0.036 | 0.000 | 0.000 |
| lear_clip_aci | da | 0.098 | 0.000 | 0.029 | 0.000 | 0.000 |
| lear_clip_aci | rt | 0.100 | 0.396 | 0.027 | 0.000 | 0.000 |
| lear_wx | da | 0.115 | 0.000 | 0.041 | 0.000 | 0.000 |
| lear_wx | rt | 0.118 | 0.000 | 0.036 | 0.000 | 0.000 |
| lear_wx_clip | da | 0.115 | 0.000 | 0.041 | 0.000 | 0.000 |
| lear_wx_clip | rt | 0.118 | 0.000 | 0.036 | 0.000 | 0.000 |
| lear_wx_clip_aci | da | 0.099 | 0.004 | 0.029 | 0.000 | 0.000 |
| lear_wx_clip_aci | rt | 0.100 | 0.785 | 0.027 | 0.000 | 0.000 |
| persist_da_d1 | da | 0.104 | 0.000 | 0.032 | 0.000 | 0.000 |
| persist_da_d1 | rt | 0.107 | 0.000 | 0.032 | 0.000 | 0.000 |
| persist_rt_d2 | da | 0.108 | 0.000 | 0.032 | 0.000 | 0.000 |
| persist_rt_d2 | rt | 0.106 | 0.000 | 0.032 | 0.000 | 0.000 |
| weekly_da_d7 | da | 0.112 | 0.000 | 0.032 | 0.000 | 0.000 |
| weekly_da_d7 | rt | 0.111 | 0.000 | 0.033 | 0.000 | 0.000 |

## Backtest-overfitting and multiple-testing diagnostics

Applied to daily forecast *skill*: benchmark daily CRPS − model daily CRPS ($/MWh, total price, averaged over the day's scored hours and zones). SR = non-annualized Sharpe ratio of that daily skill. Trials = every configuration in the registry. All values are descriptive; none is used to accept or reject a model.

- **PSR(0)**: probability the true skill SR > 0 given sample length, skew and kurtosis (Bailey & López de Prado 2012).
- **DSR**: PSR against SR0, the expected maximum SR from the implied number of independent trials (Bailey & López de Prado 2014).
- **MinTRL**: days of track record needed for PSR(0) to reach 95% at the observed SR, skew and kurtosis.
- **DM p (Holm / BHY)**: Diebold–Mariano p-values adjusted for testing every trial (Harvey, Liu & Zhu 2016).
- **SPA / Reality Check**: p-value for H0 'no trial beats the benchmark', accounting for the search over all trials (Hansen 2005; White 2000; stationary bootstrap, mean block 10 days).
- **PBO**: probability that the configuration with the best in-sample mean skill ranks below the median out-of-sample, from CSCV with S=16 blocks (Bailey, Borwein, López de Prado & Zhu 2017). With few trials PBO is coarse and varies a lot between samples.

Reading notes:

- DSR assumes the trials are variants from one search (e.g. hyper-parameter settings of one model). Mixing deliberately different benchmarks inflates Var[SR] and hence SR0, which makes DSR conservative.
- CSCV's in-sample and out-of-sample halves are complements, so when the same trial is selected in every combination its IS and OOS means sum to twice its full-sample mean and the degradation slope is exactly −1 by construction. The slope is informative only when the selected trial changes across combinations.
- Skill series are heavy-tailed (price spikes), so PSR/DSR/MinTRL rely heavily on the kurtosis estimate.

### DA vs `lago_naive`

Days: 1065 (rows aligned across trials: True). Configurations tried: 41; avg correlation of trial skill series: 0.858; implied independent trials N̂ = 6.68; Var[SR] across trials = 0.02230; SR0 (expected max SR under no skill) = 0.2033.

| model | T | mean_skill | sd_skill | sr | skew | kurt | psr_0 | dsr | min_trl_days_95 | dm_p | dm_p_holm | dm_p_bhy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| assemble_v1_final | 1,065 | 3.807 | 14.448 | 0.264 | 8.147 | 98.097 | 1.000 | 0.996 | 21.988 | 0.000 | 0.000 | 0.000 |
| assemble_v1e_v2c_aci | 1,065 | 3.898 | 14.487 | 0.269 | 8.269 | 96.059 | 1.000 | 0.999 | 19.523 | 0.000 | 0.000 | 0.000 |
| combo2_eq_aci | 1,065 | 4.243 | 14.576 | 0.291 | 8.289 | 99.306 | 1.000 | 1.000 | 22.377 | 0.000 | 0.000 | 0.000 |
| combo2_inv_aci | 1,065 | 4.237 | 14.571 | 0.291 | 8.291 | 99.412 | 1.000 | 1.000 | 22.417 | 0.000 | 0.000 | 0.000 |
| combo3_eq_aci | 1,065 | 4.648 | 14.951 | 0.311 | 8.137 | 92.044 | 1.000 | 1.000 | 19.762 | 0.000 | 0.000 | 0.000 |
| combo3wx_eq_aci | 1,065 | 4.605 | 15.129 | 0.304 | 7.837 | 87.341 | 1.000 | 1.000 | 18.938 | 0.000 | 0.000 | 0.000 |
| gbm_l1 | 1,065 | 3.476 | 14.771 | 0.235 | 7.862 | 97.480 | 1.000 | 0.933 | 24.720 | 0.000 | 0.000 | 0.000 |
| gbm_l1_aci | 1,065 | 3.631 | 14.727 | 0.247 | 7.908 | 96.312 | 1.000 | 0.977 | 23.193 | 0.000 | 0.000 | 0.000 |
| gbm_l1_v3 | 1,065 | 3.344 | 15.046 | 0.222 | 7.556 | 91.075 | 1.000 | 0.827 | 24.719 | 0.000 | 0.000 | 0.000 |
| gbm_l1_v3_aci | 1,065 | 3.543 | 14.970 | 0.237 | 7.679 | 90.923 | 1.000 | 0.950 | 22.336 | 0.000 | 0.000 | 0.000 |
| gbm_l2 | 1,065 | 3.641 | 14.880 | 0.245 | 8.107 | 95.997 | 1.000 | 0.979 | 20.801 | 0.000 | 0.000 | 0.000 |
| lago_naive | 1,065 | 0.000 | 0.000 | nan | nan | nan | nan | nan | inf | nan | nan | nan |
| lear | 1,065 | 4.033 | 15.023 | 0.268 | 7.973 | 89.826 | 1.000 | 0.999 | 18.271 | 0.000 | 0.000 | 0.000 |
| lear2 | 1,065 | 3.780 | 14.515 | 0.260 | 8.532 | 103.284 | 1.000 | 0.995 | 21.438 | 0.000 | 0.000 | 0.000 |
| lear2_aci | 1,065 | 3.898 | 14.538 | 0.268 | 8.419 | 100.167 | 1.000 | 0.998 | 20.755 | 0.000 | 0.000 | 0.000 |
| lear2_long_aci | 1,065 | 4.038 | 14.684 | 0.275 | 8.360 | 96.992 | 1.000 | 0.999 | 19.452 | 0.000 | 0.000 | 0.000 |
| lear_clip | 1,065 | 4.287 | 14.960 | 0.287 | 8.102 | 91.660 | 1.000 | 1.000 | 18.776 | 0.000 | 0.000 | 0.000 |
| lear_clip_aci | 1,065 | 4.397 | 15.014 | 0.293 | 8.025 | 89.794 | 1.000 | 1.000 | 18.466 | 0.000 | 0.000 | 0.000 |
| lear_wx | 1,065 | 4.280 | 15.131 | 0.283 | 7.886 | 87.644 | 1.000 | 1.000 | 17.990 | 0.000 | 0.000 | 0.000 |
| lear_wx_clip | 1,065 | 4.280 | 15.131 | 0.283 | 7.886 | 87.644 | 1.000 | 1.000 | 17.990 | 0.000 | 0.000 | 0.000 |
| lear_wx_clip_aci | 1,065 | 4.390 | 15.191 | 0.289 | 7.835 | 86.231 | 1.000 | 1.000 | 17.690 | 0.000 | 0.000 | 0.000 |
| persist_da_d1 | 1,065 | 2.541 | 14.657 | 0.173 | 7.773 | 108.528 | 1.000 | 0.075 | 42.452 | 0.000 | 0.000 | 0.000 |
| persist_rt_d2 | 1,065 | -4.078 | 20.988 | -0.194 | -2.448 | 83.955 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| weekly_da_d7 | 1,065 | -4.179 | 14.733 | -0.284 | -4.789 | 34.722 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |

SPA p-values (lower / consistent / upper): 0.000 / 0.000 / 0.000; Reality Check p: 0.000 (23 trials, 2000 bootstrap draws).

PBO = 0.000 over 24 trials (12,870 CSCV combinations, 1056 days); median logit 2.44; performance degradation slope -1.00; P(selected trial's OOS mean skill < 0) = 0.000; share of quantiles where selected-OOS ≥ all-OOS = 1.00.

### RT vs `lago_naive`

Days: 1065 (rows aligned across trials: True). Configurations tried: 41; avg correlation of trial skill series: 0.841; implied independent trials N̂ = 7.37; Var[SR] across trials = 0.01184; SR0 (expected max SR under no skill) = 0.1540.

| model | T | mean_skill | sd_skill | sr | skew | kurt | psr_0 | dsr | min_trl_days_95 | dm_p | dm_p_holm | dm_p_bhy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| assemble_v1_final | 1,065 | 2.811 | 13.839 | 0.203 | 7.744 | 93.521 | 1.000 | 0.995 | 26.005 | 0.000 | 0.001 | 0.000 |
| assemble_v1e_v2c_aci | 1,065 | 2.621 | 13.393 | 0.196 | 8.365 | 101.345 | 1.000 | 0.992 | 23.870 | 0.000 | 0.001 | 0.000 |
| combo2_eq_aci | 1,065 | 3.250 | 13.903 | 0.234 | 8.216 | 96.236 | 1.000 | 1.000 | 19.833 | 0.000 | 0.000 | 0.000 |
| combo2_inv_aci | 1,065 | 3.250 | 13.904 | 0.234 | 8.213 | 96.190 | 1.000 | 1.000 | 19.844 | 0.000 | 0.000 | 0.000 |
| combo3_eq_aci | 1,065 | 3.386 | 13.903 | 0.244 | 8.227 | 96.420 | 1.000 | 1.000 | 19.758 | 0.000 | 0.000 | 0.000 |
| combo3wx_eq_aci | 1,065 | 3.405 | 13.937 | 0.244 | 8.143 | 94.503 | 1.000 | 1.000 | 19.400 | 0.000 | 0.000 | 0.000 |
| gbm_l1 | 1,065 | 2.699 | 14.112 | 0.191 | 8.029 | 96.653 | 1.000 | 0.982 | 26.079 | 0.000 | 0.001 | 0.001 |
| gbm_l1_aci | 1,065 | 2.908 | 13.937 | 0.209 | 8.152 | 97.028 | 1.000 | 0.999 | 22.390 | 0.000 | 0.001 | 0.000 |
| gbm_l1_v3 | 1,065 | 2.649 | 14.063 | 0.188 | 8.083 | 96.995 | 1.000 | 0.975 | 26.077 | 0.000 | 0.001 | 0.001 |
| gbm_l1_v3_aci | 1,065 | 2.860 | 13.921 | 0.205 | 8.072 | 95.355 | 1.000 | 0.998 | 22.614 | 0.000 | 0.001 | 0.000 |
| gbm_l2 | 1,065 | 0.676 | 15.779 | 0.043 | 1.854 | 55.112 | 0.925 | 0.000 | 1393.562 | 0.182 | 0.546 | 0.744 |
| lago_naive | 1,065 | 0.000 | 0.000 | nan | nan | nan | nan | nan | inf | nan | nan | nan |
| lear | 1,065 | 2.663 | 13.997 | 0.190 | 8.018 | 95.089 | 1.000 | 0.981 | 25.366 | 0.000 | 0.001 | 0.001 |
| lear2 | 1,065 | 2.457 | 13.880 | 0.177 | 8.293 | 100.180 | 1.000 | 0.912 | 27.673 | 0.000 | 0.001 | 0.001 |
| lear2_aci | 1,065 | 2.664 | 13.736 | 0.194 | 8.287 | 98.951 | 1.000 | 0.990 | 23.577 | 0.000 | 0.001 | 0.001 |
| lear2_long_aci | 1,065 | 2.837 | 13.788 | 0.206 | 8.271 | 98.098 | 1.000 | 0.998 | 21.833 | 0.000 | 0.001 | 0.000 |
| lear_clip | 1,065 | 2.727 | 13.984 | 0.195 | 8.060 | 95.721 | 1.000 | 0.990 | 24.385 | 0.000 | 0.001 | 0.001 |
| lear_clip_aci | 1,065 | 2.912 | 13.856 | 0.210 | 8.096 | 95.216 | 1.000 | 0.999 | 21.751 | 0.000 | 0.001 | 0.000 |
| lear_wx | 1,065 | 2.757 | 14.018 | 0.197 | 7.885 | 93.372 | 1.000 | 0.991 | 24.957 | 0.000 | 0.001 | 0.001 |
| lear_wx_clip | 1,065 | 2.757 | 14.018 | 0.197 | 7.885 | 93.372 | 1.000 | 0.991 | 24.957 | 0.000 | 0.001 | 0.001 |
| lear_wx_clip_aci | 1,065 | 2.952 | 13.907 | 0.212 | 7.936 | 92.920 | 1.000 | 0.999 | 22.072 | 0.000 | 0.001 | 0.000 |
| persist_da_d1 | 1,065 | 1.923 | 12.873 | 0.149 | 9.433 | 133.873 | 1.000 | 0.397 | 41.277 | 0.000 | 0.001 | 0.001 |
| persist_rt_d2 | 1,065 | -2.731 | 21.881 | -0.125 | -5.934 | 138.166 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| weekly_da_d7 | 1,065 | -2.461 | 13.368 | -0.184 | -3.347 | 36.113 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |

SPA p-values (lower / consistent / upper): 0.000 / 0.000 / 0.000; Reality Check p: 0.000 (23 trials, 2000 bootstrap draws).

PBO = 0.003 over 24 trials (12,870 CSCV combinations, 1056 days); median logit 2.44; performance degradation slope -0.96; P(selected trial's OOS mean skill < 0) = 0.000; share of quantiles where selected-OOS ≥ all-OOS = 1.00.

### DA vs `persist_da_d1`

Days: 1065 (rows aligned across trials: True). Configurations tried: 41; avg correlation of trial skill series: 0.719; implied independent trials N̂ = 12.25; Var[SR] across trials = 0.03384; SR0 (expected max SR under no skill) = 0.3081.

| model | T | mean_skill | sd_skill | sr | skew | kurt | psr_0 | dsr | min_trl_days_95 | dm_p | dm_p_holm | dm_p_bhy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| assemble_v1_final | 1,065 | 1.266 | 6.893 | 0.184 | 4.371 | 86.900 | 1.000 | 0.000 | 74.885 | 0.000 | 0.000 | 0.000 |
| assemble_v1e_v2c_aci | 1,065 | 1.357 | 6.555 | 0.207 | 6.863 | 104.788 | 1.000 | 0.000 | 44.633 | 0.000 | 0.000 | 0.000 |
| combo2_eq_aci | 1,065 | 1.702 | 6.587 | 0.258 | 5.128 | 105.456 | 1.000 | 0.087 | 58.489 | 0.000 | 0.000 | 0.000 |
| combo2_inv_aci | 1,065 | 1.696 | 6.590 | 0.257 | 5.083 | 104.861 | 1.000 | 0.082 | 58.652 | 0.000 | 0.000 | 0.000 |
| combo3_eq_aci | 1,065 | 2.107 | 6.443 | 0.327 | 7.195 | 104.683 | 1.000 | 0.698 | 36.906 | 0.000 | 0.000 | 0.000 |
| combo3wx_eq_aci | 1,065 | 2.064 | 6.728 | 0.307 | 7.114 | 108.285 | 1.000 | 0.485 | 39.569 | 0.000 | 0.000 | 0.000 |
| gbm_l1 | 1,065 | 0.935 | 6.808 | 0.137 | 1.579 | 73.927 | 1.000 | 0.000 | 162.529 | 0.000 | 0.001 | 0.001 |
| gbm_l1_aci | 1,065 | 1.090 | 6.672 | 0.163 | 2.718 | 75.704 | 1.000 | 0.000 | 107.911 | 0.000 | 0.000 | 0.000 |
| gbm_l1_v3 | 1,065 | 0.803 | 7.056 | 0.114 | 2.773 | 81.145 | 1.000 | 0.000 | 198.093 | 0.004 | 0.015 | 0.016 |
| gbm_l1_v3_aci | 1,065 | 1.003 | 6.894 | 0.145 | 4.025 | 87.125 | 1.000 | 0.000 | 112.320 | 0.000 | 0.001 | 0.001 |
| gbm_l2 | 1,065 | 1.100 | 6.342 | 0.173 | 4.549 | 75.635 | 1.000 | 0.000 | 70.436 | 0.000 | 0.000 | 0.000 |
| lago_naive | 1,065 | -2.541 | 14.657 | -0.173 | -7.773 | 108.528 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| lear | 1,065 | 1.492 | 6.772 | 0.220 | 7.773 | 120.963 | 1.000 | 0.000 | 42.419 | 0.000 | 0.000 | 0.000 |
| lear2 | 1,065 | 1.239 | 7.212 | 0.172 | 4.952 | 109.526 | 1.000 | 0.000 | 88.039 | 0.000 | 0.000 | 0.000 |
| lear2_aci | 1,065 | 1.357 | 7.133 | 0.190 | 5.841 | 111.481 | 1.000 | 0.000 | 67.388 | 0.000 | 0.000 | 0.000 |
| lear2_long_aci | 1,065 | 1.497 | 6.769 | 0.221 | 7.164 | 116.913 | 1.000 | 0.001 | 47.077 | 0.000 | 0.000 | 0.000 |
| lear_clip | 1,065 | 1.747 | 6.728 | 0.260 | 8.104 | 123.896 | 1.000 | 0.054 | 39.809 | 0.000 | 0.000 | 0.000 |
| lear_clip_aci | 1,065 | 1.857 | 6.796 | 0.273 | 8.175 | 123.207 | 1.000 | 0.133 | 38.950 | 0.000 | 0.000 | 0.000 |
| lear_wx | 1,065 | 1.739 | 6.984 | 0.249 | 7.639 | 117.332 | 1.000 | 0.021 | 40.321 | 0.000 | 0.000 | 0.000 |
| lear_wx_clip | 1,065 | 1.739 | 6.984 | 0.249 | 7.639 | 117.332 | 1.000 | 0.021 | 40.321 | 0.000 | 0.000 | 0.000 |
| lear_wx_clip_aci | 1,065 | 1.850 | 7.049 | 0.262 | 7.718 | 116.581 | 1.000 | 0.064 | 38.895 | 0.000 | 0.000 | 0.000 |
| persist_da_d1 | 1,065 | 0.000 | 0.000 | nan | nan | nan | nan | nan | inf | nan | nan | nan |
| persist_rt_d2 | 1,065 | -6.619 | 19.087 | -0.347 | -11.376 | 188.910 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| weekly_da_d7 | 1,065 | -6.720 | 20.011 | -0.336 | -4.265 | 36.671 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |

SPA p-values (lower / consistent / upper): 0.000 / 0.000 / 0.000; Reality Check p: 0.030 (23 trials, 2000 bootstrap draws).

PBO = 0.000 over 24 trials (12,870 CSCV combinations, 1056 days); median logit 2.44; performance degradation slope -0.98; P(selected trial's OOS mean skill < 0) = 0.000; share of quantiles where selected-OOS ≥ all-OOS = 1.00.

### RT vs `persist_da_d1`

Days: 1065 (rows aligned across trials: True). Configurations tried: 41; avg correlation of trial skill series: 0.724; implied independent trials N̂ = 12.03; Var[SR] across trials = 0.01577; SR0 (expected max SR under no skill) = 0.2092.

| model | T | mean_skill | sd_skill | sr | skew | kurt | psr_0 | dsr | min_trl_days_95 | dm_p | dm_p_holm | dm_p_bhy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| assemble_v1_final | 1,065 | 0.888 | 8.136 | 0.109 | 4.282 | 62.016 | 1.000 | 0.000 | 163.126 | 0.006 | 0.085 | 0.052 |
| assemble_v1e_v2c_aci | 1,065 | 0.698 | 7.424 | 0.094 | 4.983 | 60.811 | 1.000 | 0.000 | 204.202 | 0.009 | 0.111 | 0.056 |
| combo2_eq_aci | 1,065 | 1.326 | 7.673 | 0.173 | 6.760 | 85.690 | 1.000 | 0.041 | 43.025 | 0.000 | 0.001 | 0.001 |
| combo2_inv_aci | 1,065 | 1.327 | 7.671 | 0.173 | 6.759 | 85.759 | 1.000 | 0.041 | 43.045 | 0.000 | 0.001 | 0.001 |
| combo3_eq_aci | 1,065 | 1.463 | 7.516 | 0.195 | 6.766 | 85.324 | 1.000 | 0.246 | 35.415 | 0.000 | 0.000 | 0.000 |
| combo3wx_eq_aci | 1,065 | 1.482 | 7.500 | 0.198 | 6.478 | 76.359 | 1.000 | 0.286 | 32.581 | 0.000 | 0.000 | 0.000 |
| gbm_l1 | 1,065 | 0.776 | 7.906 | 0.098 | 5.171 | 76.099 | 1.000 | 0.000 | 190.058 | 0.011 | 0.111 | 0.060 |
| gbm_l1_aci | 1,065 | 0.985 | 7.719 | 0.128 | 5.941 | 79.685 | 1.000 | 0.000 | 94.382 | 0.001 | 0.025 | 0.022 |
| gbm_l1_v3 | 1,065 | 0.726 | 7.652 | 0.095 | 5.255 | 70.437 | 1.000 | 0.000 | 198.786 | 0.016 | 0.111 | 0.075 |
| gbm_l1_v3_aci | 1,065 | 0.937 | 7.590 | 0.124 | 5.720 | 71.348 | 1.000 | 0.000 | 100.638 | 0.002 | 0.037 | 0.024 |
| gbm_l2 | 1,065 | -1.247 | 12.687 | -0.098 | -4.834 | 89.444 | 0.000 | 0.000 | inf | 0.983 | 1.000 | 1.000 |
| lago_naive | 1,065 | -1.923 | 12.873 | -0.149 | -9.433 | 133.873 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| lear | 1,065 | 0.740 | 7.890 | 0.094 | 5.363 | 68.116 | 1.000 | 0.000 | 199.400 | 0.015 | 0.111 | 0.075 |
| lear2 | 1,065 | 0.534 | 8.058 | 0.066 | 5.470 | 76.154 | 0.995 | 0.000 | 445.179 | 0.045 | 0.226 | 0.205 |
| lear2_aci | 1,065 | 0.741 | 7.945 | 0.093 | 5.912 | 78.656 | 1.000 | 0.000 | 193.067 | 0.011 | 0.111 | 0.060 |
| lear2_long_aci | 1,065 | 0.914 | 7.859 | 0.116 | 6.059 | 78.212 | 1.000 | 0.000 | 112.422 | 0.002 | 0.036 | 0.024 |
| lear_clip | 1,065 | 0.804 | 7.852 | 0.102 | 5.433 | 69.223 | 1.000 | 0.000 | 161.744 | 0.009 | 0.111 | 0.056 |
| lear_clip_aci | 1,065 | 0.989 | 7.763 | 0.127 | 5.793 | 71.457 | 1.000 | 0.000 | 92.353 | 0.002 | 0.030 | 0.022 |
| lear_wx | 1,065 | 0.834 | 7.905 | 0.106 | 4.951 | 62.458 | 1.000 | 0.000 | 158.558 | 0.009 | 0.111 | 0.056 |
| lear_wx_clip | 1,065 | 0.834 | 7.905 | 0.106 | 4.951 | 62.458 | 1.000 | 0.000 | 158.558 | 0.009 | 0.111 | 0.056 |
| lear_wx_clip_aci | 1,065 | 1.029 | 7.833 | 0.131 | 5.346 | 64.552 | 1.000 | 0.000 | 90.622 | 0.002 | 0.030 | 0.022 |
| persist_da_d1 | 1,065 | 0.000 | 0.000 | nan | nan | nan | nan | nan | inf | nan | nan | nan |
| persist_rt_d2 | 1,065 | -4.654 | 19.188 | -0.243 | -13.833 | 268.556 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |
| weekly_da_d7 | 1,065 | -4.384 | 18.244 | -0.240 | -4.158 | 40.831 | 0.000 | 0.000 | inf | 1.000 | 1.000 | 1.000 |

SPA p-values (lower / consistent / upper): 0.000 / 0.000 / 0.000; Reality Check p: 0.051 (23 trials, 2000 bootstrap draws).

PBO = 0.003 over 24 trials (12,870 CSCV combinations, 1056 days); median logit 2.44; performance degradation slope -0.89; P(selected trial's OOS mean skill < 0) = 0.000; share of quantiles where selected-OOS ≥ all-OOS = 1.00.

## Runs and reproducibility

| model | run_id | config_hash | code_fingerprint | git_commit | data_fingerprint | duration_s |
|---|---|---|---|---|---|---|
| assemble_v1_final | assemble_v1_final-20261005T043408-e328cd | e328cd010fdd | bc84e5f8d8f5cd41 | c72d8e7-dirty | 3041cb46ebf0afdf | 30.000 |
| assemble_v1e_v2c_aci | assemble_v1e_v2c_aci-20260928T150954-1975ce | 1975ced46313 | 0f6969122599455c | — | 4215beb03db947ac | 25.000 |
| combo2_eq_aci | combo2_eq_aci-20260928T051453-dab2a8 | dab2a8effaf4 | 76c515fa2c47f8c7 | — | 4215beb03db947ac | 29.000 |
| combo2_inv_aci | combo2_inv_aci-20260928T052135-c30e29 | c30e29221409 | 76c515fa2c47f8c7 | — | 4215beb03db947ac | 29.000 |
| combo3_eq_aci | combo3_eq_aci-20260928T145307-9a2801 | 9a28010c9e5d | 9b056927467044b5 | — | 4215beb03db947ac | 27.000 |
| combo3wx_eq_aci | combo3wx_eq_aci-20261005T040957-338a1f | 338a1ff168d5 | a67669723ec2afa8 | 317400c-dirty | 3041cb46ebf0afdf | 27.000 |
| gbm_l1 | gbm_l1-20260928T024002-cb6de8 | cb6de888cfc1 | 034577d32368dc5d | — | 4215beb03db947ac | 895.000 |
| gbm_l1_aci | gbm_l1_aci-20260928T050834-07fb62 | 07fb628a3893 | 76c515fa2c47f8c7 | — | 4215beb03db947ac | 25.000 |
| gbm_l1_v3 | gbm_l1_v3-20261005T022351-b00727 | b00727fc2fca | a67669723ec2afa8 | d479e00-dirty | 3041cb46ebf0afdf | 1131.000 |
| gbm_l1_v3_aci | gbm_l1_v3_aci-20261005T040301-bf6a08 | bf6a0841c929 | a67669723ec2afa8 | 317400c-dirty | 3041cb46ebf0afdf | 30.000 |
| gbm_l2 | gbm_l2-20260928T025515-77d543 | 77d543eebe30 | 1526060d96d32d38 | — | 4215beb03db947ac | 701.000 |
| lago_naive | lago_naive-20260928T015624-a64700 | a647000aa0ef | 8389510305d61aa5 | — | 4215beb03db947ac | 106.000 |
| lear | lear-20260928T030707-d13937 | d13937e11d8b | 1526060d96d32d38 | — | 4215beb03db947ac | 2950.000 |
| lear2 | lear2-20260928T044044-d6a347 | d6a347ffe3fa | 76c515fa2c47f8c7 | — | 4215beb03db947ac | 912.000 |
| lear2_aci | lear2_aci-20260928T050201-bced21 | bced21e27858 | 76c515fa2c47f8c7 | — | 4215beb03db947ac | 26.000 |
| lear2_long_aci | lear2_long_aci-20260928T150231-ada64d | ada64dae35f0 | 0f6969122599455c | — | 4215beb03db947ac | 36.000 |
| lear_clip | lear_clip-20260928T042346-fc5edf | fc5edf9f190f | 810d4634ab806008 | — | 4215beb03db947ac | 27.000 |
| lear_clip_aci | lear_clip_aci-20260928T043018-0c3a4b | 0c3a4b21db13 | 810d4634ab806008 | — | 4215beb03db947ac | 31.000 |
| lear_wx | lear_wx-20261005T025430-8d3baa | 8d3baa6c1463 | a67669723ec2afa8 | d479e00-dirty | 3041cb46ebf0afdf | 3252.000 |
| lear_wx_clip | lear_wx_clip-20261005T034945-42771e | 42771ea5ecd3 | a67669723ec2afa8 | 317400c-dirty | 3041cb46ebf0afdf | 29.000 |
| lear_wx_clip_aci | lear_wx_clip_aci-20261005T035627-fba7e4 | fba7e4ec5c53 | a67669723ec2afa8 | 317400c-dirty | 3041cb46ebf0afdf | 32.000 |
| persist_da_d1 | persist_da_d1-20260928T015250-1931b2 | 1931b2db7566 | 8389510305d61aa5 | — | 4215beb03db947ac | 108.000 |
| persist_rt_d2 | persist_rt_d2-20260928T015810-d065a4 | d065a41849f4 | 8389510305d61aa5 | — | 4215beb03db947ac | 105.000 |
| struct_cong | struct_cong-20260928T145609-95ef67 | 95ef67db4ed3 | 0f6969122599455c | — | 4215beb03db947ac | 592.000 |
| struct_cong_l2 | struct_cong_l2-20260928T184407-cf60b1 | cf60b1d572a2 | 5e52f89de0c00f28 | — | 4215beb03db947ac | 759.000 |
| struct_cong_out | struct_cong_out-20261002T174101-7631cc | 7631cc5abe2b | 2ab9155327f72b0d | 7fd6907 | 3041cb46ebf0afdf | 1461.000 |
| weekly_da_d7 | weekly_da_d7-20260928T015439-699916 | 699916acd725 | 8389510305d61aa5 | — | 4215beb03db947ac | 105.000 |
| zero_congestion | zero_congestion-20260928T183239-323488 | 323488129c81 | 43a06ad53f628181 | — | 4215beb03db947ac | 77.000 |

> git_commit “—”: the run predates the repository's first commit (2026-09-28 15:25 ET), so it is identified by code_fingerprint only; no commit reproduces it exactly.

> Note: the compared runs used 12 different code versions (code_fingerprint).

> Note: the compared runs used 2 different panel data versions (data_fingerprint).

All logged runs (every trial counts toward the DSR):

| status | runs | configs |
|---|---|---|
| failed | 3 | 3 |
| aborted | 1 | 1 |
| done | 38 | 33 |
| exploratory | 7 | 7 |
