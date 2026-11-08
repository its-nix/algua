"""Fixed weekly momentum for the approved midcap machinery demo; no investability claim."""

from __future__ import annotations

from typing import Any

import pandas as pd

from algua.contracts.types import ExecutionContract
from algua.strategies.base import StrategyConfig

GENERATED_BY = "agent"

# Observed current-membership/liquidity sample, 2026-11-08. Never historical PIT membership.
CONFIG = StrategyConfig(
    name="midcap_weekly_momentum_smoke",
    universe="""
        AA AAL ACI ADC AEIS AGCO AHR ALGM ALK ALLY ALV AM AMG AMH AMKR AN ANF APG APPF AR ARMK
        ARW ARWR ASH ATI ATR AVAV AVNT AVT AVTR AXTA BAH BBWI BILL BIO BJ BKH BMRN BRKR BROS
        BRX BSY BTSG BURL BWA BWXT BYD CACI CART CAVA CBT CCK CDE CDP CELH CFR CG CGNX CHDN
        CHE CHRD CHWY CLF CLH CMC CNH CNX COKE COLB CORT CRBG CROX CRS CRUS CSL CTRE CTVA CUBE
        CUZ CVLT CW CYTK DAR DBX DINO DKS DOCN DOCS DOCU DT DTM DUOL DY EAT EGP EHC ELAN ELF
        ELS ENSG ENTG EPR EQH EVR EWBC EXEL EXP FCFS FHN FIVE FLG FLR FLS FN FNB FND FNF FORM
        FOUR FR FTI GAP GEF GGG GKOS GLPI GME GMED GPK GWRE H HAE HALO HIMS HL HLI HQY HR HRB
        HUBS IDA INGR IRT ITT JAZZ JEF JLL KNF KNSL KNX KRC KRG KRYS KTOS LAD LAMR LECO LFUS
        LIVN LNTH LSCC M MANH MEDP MKSI MOG-A MOH MP MTDR MTN MTSI MTZ MUR MUSA MZTI NBIX NEU
        NFG NJR NLY NNN NOV NTNX NVST NVT NWE NXST NXT NYT OC OGE OGS OHI OLLI ONB ONTO OPCH
        ORA OVV OZK PAG PATH PB PBF PEGA PEN PFGC PINS PK PLNT PNFP POR POST PPC PR QLYS RBA
        RBC REXR RGA RGEN RGLD RH RMBS RNR ROIV ROKU RPM RRC RRX RS RYAN RYN SAIA SANM SBRA
        SCI SEIC SF SFM SGI SHC SIRI SITM SLAB SLGN SMG SMTC SN SNX SOLS SON SR SSB STAG STRL
        STWD SUI SWX SYNA THC THG TKR TLN TOL TOST TRU TTMI TXNM TXRH UGI UMBF UNM USFD UTHR
        VAL VFC VIAV VICR VLY VNO VNOM VOYA VVV WAL WCC WEX WFRD WH WHR WING WLK WMG WPC WSO
        WTFC WTRG WWD XPO ZION
    """.split(),
    execution=ExecutionContract(
        rebalance_frequency="1d",
        decision_lag_bars=1,
        max_weight_per_symbol=0.075,
        fees=0.0005,
        slippage=0.0005,
    ),
    params={"lookback": 20},
    construction="top_k_equal_weight",
    construction_params={"top_k": 20},
    feature_lookback=30,
)


def signal(view: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    """Rank from the latest completed Friday anchor, retaining the basket during the week."""
    wide = view.reset_index().pivot(index="timestamp", columns="symbol", values="adj_close")
    wide = wide.sort_index()
    latest = wide.index[-1]
    anchor = latest.normalize() - pd.Timedelta(days=(latest.weekday() - 4) % 7)
    history = wide.loc[:anchor]
    lookback = int(params["lookback"])
    if len(history) <= lookback:
        return pd.Series(dtype="float64")
    return (history.iloc[-1] / history.iloc[-1 - lookback] - 1.0).dropna()


def signal_panel(bars: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """The same closed-Friday score vectorized; the engine independently verifies parity."""
    wide = bars.reset_index().pivot(index="timestamp", columns="symbol", values="adj_close")
    wide = wide.sort_index()
    scores = wide / wide.shift(int(params["lookback"])) - 1.0
    anchors = wide.index.normalize() - pd.to_timedelta((wide.index.weekday - 4) % 7, unit="D")
    positions = wide.index.searchsorted(anchors, side="right") - 1
    result = scores.iloc[positions.clip(0, None)].copy()
    result.index = wide.index
    result.loc[positions < 0, :] = float("nan")
    return result
