"""Preamp configuration registry for 8401HR devices.

Maps preamp model numbers (e.g. ``"8406-SE3"``) to per-channel hardware
settings so that a user can specify a model in a TOML config file and have all
device parameters set automatically.

Translated from the C++ reference implementation in
``p8401_HS_Configuration.h/.cpp``.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# C++ constant equivalents
# ---------------------------------------------------------------------------

DC_BIAS = 0
DC_AGROUND = 1

HP_0_5HZ = 0
HP_1HZ = 1
HP_10HZ = 2
NO_HP = 3

SLEEP_GAIN = 100
SEIZURE_RAT_GAIN = 10
SINGLE_BIO_PREAMP_GAIN = 14940.0
OXYGEN_PREAMP_GAIN = 2988.0

_ACCEL_DIVIDER = 32.0 / 165.4
ACCELEROMETER_OFFSET = 1.5 * (1.0 - _ACCEL_DIVIDER)
ACCEL_GAIN_RANGE_5 = 1_000_000.0 * 0.174 * (1.0 - _ACCEL_DIVIDER)
ACCEL_GAIN_RANGE_2 = 1_000_000.0 * 0.420 * (1.0 - _ACCEL_DIVIDER)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelConfig:
    """Per-channel hardware and metadata settings."""
    label: str
    unit: str
    dc_mode: int
    highpass: int
    lowpass: float
    preamp_gain: float | None
    bias: float
    ss_gain: int
    ss_highpass: float
    stream_type: str
    invert: bool


@dataclass(frozen=True)
class PreampConfig:
    """Full 4-primary-channel preamp configuration."""
    name: str
    channels: tuple[ChannelConfig, ChannelConfig, ChannelConfig, ChannelConfig]
    sample_rate: int = 2000
    single_bias: bool = True


# ---------------------------------------------------------------------------
# Reusable base channel templates
# ---------------------------------------------------------------------------

_EEG = ChannelConfig(
    label="EEG", unit="uV", dc_mode=DC_AGROUND, highpass=HP_0_5HZ,
    lowpass=40, preamp_gain=SLEEP_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EEG", invert=False,
)

_EEG_SE = ChannelConfig(
    label="EEG SE", unit="uV", dc_mode=DC_AGROUND, highpass=HP_1HZ,
    lowpass=1000, preamp_gain=SEIZURE_RAT_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EEG", invert=False,
)

_EEG_SE_x100 = ChannelConfig(
    label="EEG SEx100", unit="uV", dc_mode=DC_AGROUND, highpass=HP_1HZ,
    lowpass=1000, preamp_gain=SLEEP_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EEG", invert=False,
)

_EMG = ChannelConfig(
    label="EMG", unit="uV", dc_mode=DC_AGROUND, highpass=HP_10HZ,
    lowpass=100, preamp_gain=SLEEP_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EMG", invert=False,
)

_EMG_SE = ChannelConfig(
    label="EMG SE", unit="uV", dc_mode=DC_AGROUND, highpass=HP_10HZ,
    lowpass=100, preamp_gain=SEIZURE_RAT_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EMG", invert=False,
)

_BIO = ChannelConfig(
    label="BIO", unit="nA", dc_mode=DC_BIAS, highpass=NO_HP,
    lowpass=21, preamp_gain=None, bias=0.6,
    ss_gain=1, ss_highpass=0.0, stream_type="BIO", invert=False,
)

_BIO_ONLY_ONE = ChannelConfig(
    label="BIO", unit="nA", dc_mode=DC_AGROUND, highpass=NO_HP,
    lowpass=21, preamp_gain=None, bias=0.6,
    ss_gain=1, ss_highpass=0.0, stream_type="BIO", invert=False,
)

_OXYGEN = ChannelConfig(
    label="OXY", unit="nA", dc_mode=DC_AGROUND, highpass=NO_HP,
    lowpass=21, preamp_gain=None, bias=0.6,
    ss_gain=1, ss_highpass=0.0, stream_type="BIO", invert=False,
)

_UNUSED = ChannelConfig(
    label="Unused", unit="", dc_mode=DC_AGROUND, highpass=NO_HP,
    lowpass=100, preamp_gain=None, bias=0.6,
    ss_gain=5, ss_highpass=0.5, stream_type="UNUSED", invert=False,
)

_EEG_PSYCHO = ChannelConfig(
    label="EEG", unit="uV", dc_mode=DC_AGROUND, highpass=HP_0_5HZ,
    lowpass=500, preamp_gain=SEIZURE_RAT_GAIN, bias=0.0,
    ss_gain=5, ss_highpass=0.5, stream_type="EEG", invert=False,
)

_BIO_LAB = ChannelConfig(
    label="BIO LAB", unit="nA", dc_mode=DC_AGROUND, highpass=NO_HP,
    lowpass=10.5, preamp_gain=None, bias=0.6,
    ss_gain=1, ss_highpass=0.0, stream_type="BIO", invert=False,
)

_ACCEL_EMG = ChannelConfig(
    label="ACCEL", unit="g", dc_mode=DC_BIAS, highpass=NO_HP,
    lowpass=100, preamp_gain=None, bias=ACCELEROMETER_OFFSET,
    ss_gain=1, ss_highpass=0.0, stream_type="EMG", invert=False,
)


def _ch(base: ChannelConfig, label: str | None = None,
        invert: bool = False) -> ChannelConfig:
    """Derive a channel config from *base* with optional overrides."""
    if label is None and not invert:
        return base
    return ChannelConfig(
        label=label if label is not None else base.label,
        unit=base.unit, dc_mode=base.dc_mode, highpass=base.highpass,
        lowpass=base.lowpass, preamp_gain=base.preamp_gain, bias=base.bias,
        ss_gain=base.ss_gain, ss_highpass=base.ss_highpass,
        stream_type=base.stream_type, invert=invert,
    )


# ---------------------------------------------------------------------------
# Preamp configuration definitions
# ---------------------------------------------------------------------------

# -- Standard configs -------------------------------------------------------

EEG_EMG_BIO_CONFIG = PreampConfig(
    name="BIO EEGx2 EMG",
    channels=(
        _ch(_BIO),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EMG),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

EEG_3_BIO_CONFIG = PreampConfig(
    name="EEG x3 BIO",
    channels=(
        _ch(_BIO),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EEG, "EEG 3"),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

EEG_4_CONFIG = PreampConfig(
    name="EEG x4",
    channels=(
        _ch(_EEG, "EEG 4"),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EEG, "EEG 3"),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

EEG_4_SE_MOUSE_CONFIG = PreampConfig(
    name="EEG x4 SE x100",
    channels=(
        _ch(_EEG_SE_x100, "EEG 4 SEx100"),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100"),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

EEG_4_KAPLAN_CONFIG = PreampConfig(
    name="EEG x4 SE Ref",
    channels=(
        _ch(_EEG_SE_x100, "EEG 4 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

EEG_4_KAPLAN_RAT_CONFIG = PreampConfig(
    name="EEG x4 SE Ref Rat",
    channels=(
        _ch(_EEG_SE, "EEG 4 SE"),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

EEG_4_RAT_SEIZURE_CONFIG = PreampConfig(
    name="EEG x4 RAT SE",
    channels=(
        _ch(_EEG_SE, "EEG 4 SE"),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

EEG_3_BIO_RAT_CONFIG = PreampConfig(
    name="EEG x3 BIO Rat",
    channels=(
        _ch(_BIO),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

EEG_EMG_BIO_RAT_SE_CONFIG = PreampConfig(
    name="BIO EEGx2 EMG Rat SE",
    channels=(
        _ch(_BIO),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EMG_SE),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

BIO_2_EEG_EMG_CONFIG = PreampConfig(
    name="BIO x2 EEG EMG",
    channels=(
        _ch(_BIO, "BIO 1"),
        _ch(_EEG),
        _ch(_EMG),
        _ch(_BIO, "BIO 2"),
    ),
)

BIO_2_EEG_2_SE_CONFIG = PreampConfig(
    name="BIO x2 EEGx2 SE",
    channels=(
        _ch(_BIO, "BIO 1"),
        _ch(_BIO, "BIO 2"),
        _ch(_EEG_SE, "EEG 1 SE"),
        _ch(_EEG_SE, "EEG 2 SE"),
    ),
)

BIO_2_CONFIG = PreampConfig(
    name="BIOx2",
    channels=(
        _ch(_BIO, "BIO 1"),
        _ch(_BIO, "BIO 2"),
        _ch(_UNUSED),
        _ch(_UNUSED),
    ),
)

BIO_1_OX_1_CONFIG = PreampConfig(
    name="BIOx1 Ox1",
    channels=(
        _ch(_OXYGEN),
        _ch(_BIO, "BIO 1"),
        _ch(_UNUSED),
        _ch(_UNUSED),
    ),
)

BIO_4_CONFIG = PreampConfig(
    name="Calibration BIOx4",
    channels=(
        _ch(_BIO_ONLY_ONE, "BIO 1"),
        _ch(_BIO_ONLY_ONE, "BIO 2"),
        _ch(_BIO_ONLY_ONE, "BIO 3"),
        _ch(_BIO_ONLY_ONE, "BIO 4"),
    ),
    single_bias=False,
)

BIO_4_LAB_CONFIG = PreampConfig(
    name="BIO LAB x4",
    channels=(
        _ch(_BIO_LAB, "BIO LAB 1"),
        _ch(_BIO_LAB, "BIO LAB 2"),
        _ch(_BIO_LAB, "BIO LAB 3"),
        _ch(_BIO_LAB, "BIO LAB 4"),
    ),
    sample_rate=10000,
    single_bias=False,
)

EEG_3_EMG_SE_CONFIG = PreampConfig(
    name="EEG x3 EMG SE",
    channels=(
        _ch(_EMG),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100"),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

EEG_3_EMG_SE_RAT_CONFIG = PreampConfig(
    name="EEG x3 EMG Rat SE",
    channels=(
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EMG_SE),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

EEG_3_EMG_SE_10X_MOUSE_CONFIG = PreampConfig(
    name="EEG x3 EMG Mouse SE x10",
    channels=(
        _ch(_EMG_SE),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

# -- Muxed configs ----------------------------------------------------------

EEGx3_BIOx2_CONFIG = PreampConfig(
    name="EEG x3 BIO x2",
    channels=(
        _ch(_BIO, "BIO 1"),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EEG, "EEG 3"),
        _ch(_EEG, "EEG 2"),
    ),
)

EEGx2_EMG_BIOx2_CONFIG = PreampConfig(
    name="EEG x2 EMG BIO x2",
    channels=(
        _ch(_BIO, "BIO 1"),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EMG),
        _ch(_EEG, "EEG 2"),
    ),
)

# -- OGIM / Opto configs ---------------------------------------------------

OPTO_EEG_EMG_SL_CONFIG = PreampConfig(
    name="Opto EEGx2 EMG SL",
    channels=(
        _ch(_UNUSED),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EMG),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

OPTO_3EEG_SE_CONFIG = PreampConfig(
    name="Opto EEGx3 SE",
    channels=(
        _ch(_UNUSED),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100"),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

OPTO_4EEG_SE_CONFIG = PreampConfig(
    name="Opto EEGx4 SE",
    channels=(
        _ch(_EEG_SE_x100, "EEG 4 SEx100"),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100"),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

OPTO_EEG_EMG_BIO_SL_CONFIG = PreampConfig(
    name="Opto BIO EEGx2 EMG SL",
    channels=(
        _ch(_BIO),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EMG),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

OPTO_EEG_3_BIO_SE_CONFIG = PreampConfig(
    name="Opto EEG x3 BIO SE",
    channels=(
        _ch(_BIO),
        _ch(_EEG_SE_x100, "EEG 1 SEx100", invert=True),
        _ch(_EEG_SE_x100, "EEG 3 SEx100"),
        _ch(_EEG_SE_x100, "EEG 2 SEx100", invert=True),
    ),
)

OPTO_RAT_3EEG_SE_CONFIG = PreampConfig(
    name="Opto Rat EEGx3 SE",
    channels=(
        _ch(_UNUSED),
        _ch(_EEG_SE, "EEG 1 SE"),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE"),
    ),
)

OPTO_RAT_4EEG_SE_CONFIG = PreampConfig(
    name="Opto Rat EEGx4 SE",
    channels=(
        _ch(_EEG_SE, "EEG 4 SE"),
        _ch(_EEG_SE, "EEG 1 SE"),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE"),
    ),
)

OPTO_RAT_EEG_3_BIO_SE_CONFIG = PreampConfig(
    name="Opto Rat EEG x3 BIO SE",
    channels=(
        _ch(_BIO),
        _ch(_EEG_SE, "EEG 1 SE"),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE"),
    ),
)

# -- Specialty / no-ID-resistor configs -------------------------------------

EEG_3_8201_SS_CONFIG = PreampConfig(
    name="EEG x3 8201 SS",
    channels=(
        _ch(_UNUSED),
        _ch(_EEG_PSYCHO, "1 PCX", invert=True),
        _ch(_EEG_PSYCHO, "3 EMG"),
        _ch(_EEG_PSYCHO, "2 FCX", invert=True),
    ),
)

EEG_3_8201_DEP_CONFIG = PreampConfig(
    name="EEG x3 8201 DEP",
    channels=(
        _ch(_UNUSED),
        _ch(_EEG_PSYCHO, "1 PCx", invert=True),
        _ch(_EEG_PSYCHO, "3 HPC"),
        _ch(_EEG_PSYCHO, "2 FCx", invert=True),
    ),
)

# -- Accelerometer configs --------------------------------------------------

EEG_3_ACCEL_CONFIG = PreampConfig(
    name="EEG x3 ACCEL",
    channels=(
        _ch(_ACCEL_EMG),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EEG, "EEG 3"),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

EEG_EMG_ACCEL_CONFIG = PreampConfig(
    name="EEG x2 EMG ACCEL",
    channels=(
        _ch(_ACCEL_EMG),
        _ch(_EEG, "EEG 1", invert=True),
        _ch(_EMG),
        _ch(_EEG, "EEG 2", invert=True),
    ),
)

EEG_EMG_RAT_ACCEL_CONFIG = PreampConfig(
    name="EEG x2 EMG RAT ACCEL",
    channels=(
        _ch(_ACCEL_EMG),
        _ch(_EEG_SE, "EEG 1 SE", invert=True),
        _ch(_EMG_SE),
        _ch(_EEG_SE, "EEG 2 SE", invert=True),
    ),
)

EEG_3_RAT_ACCEL_CONFIG = PreampConfig(
    name="EEG x3 RAT ACCEL",
    channels=(
        _ch(_ACCEL_EMG),
        _ch(_EEG_SE, "EEG 1 SE"),
        _ch(_EEG_SE, "EEG 3 SE"),
        _ch(_EEG_SE, "EEG 2 SE"),
    ),
)


# ---------------------------------------------------------------------------
# Registry: model number string  ->  PreampConfig
# ---------------------------------------------------------------------------

def _build_registry() -> dict[str, PreampConfig]:
    """Build the model-number lookup table.

    Model numbers are normalized to upper-case with whitespace stripped.
    Where a C++ configuration lists multiple models separated by ``,`` or
    ``;``, each is registered individually.  When the same model number
    appears in more than one configuration, the first registration wins.
    """
    reg: dict[str, PreampConfig] = {}

    entries: list[tuple[str, PreampConfig]] = [
        # Standard
        ("8407-SL, 8406-SE, 8406-SL",  EEG_EMG_BIO_CONFIG),
        ("8406-SE3",                    EEG_3_BIO_CONFIG),
        ("8407-SE4, 8406-SE4-10",       EEG_4_CONFIG),
        ("8406-SE4",                    EEG_4_SE_MOUSE_CONFIG),
        ("8406-SE4-Ref",                EEG_4_KAPLAN_CONFIG),
        ("8407-SE4-Ref, 8406-SE4-Ref-10", EEG_4_KAPLAN_RAT_CONFIG),
        ("8407-SE3, 8406-SE3-10",       EEG_3_BIO_RAT_CONFIG),
        ("8407-SE",                     EEG_EMG_BIO_RAT_SE_CONFIG),
        ("8407-SL-2BIO",                BIO_2_EEG_EMG_CONFIG),
        ("8407-SE2-2BIO",               BIO_2_EEG_2_SE_CONFIG),
        ("8406-2BIO, 8407-2BIO",        BIO_2_CONFIG),
        ("8406-1BIO1Ox",                BIO_1_OX_1_CONFIG),
        ("7052",                        BIO_4_CONFIG),
        ("Lab Calibration",             BIO_4_LAB_CONFIG),
        ("8406-SE31M",                  EEG_3_EMG_SE_CONFIG),
        ("8407-SE31M",                  EEG_3_EMG_SE_RAT_CONFIG),
        ("8406-SE31M-10",               EEG_3_EMG_SE_10X_MOUSE_CONFIG),
        ("8407-SE4-Seizure",            EEG_4_RAT_SEIZURE_CONFIG),
        # Muxed
        ("8406-5SE3",                   EEGx3_BIOx2_CONFIG),
        ("8406-5SL, 8406-5SE",          EEGx2_EMG_BIOx2_CONFIG),
        # OGIM / Opto (mouse)
        ("8486-1optSL",                 OPTO_EEG_EMG_SL_CONFIG),
        ("8486-1optSE3",                OPTO_3EEG_SE_CONFIG),
        ("8486-1optSE4",                OPTO_4EEG_SE_CONFIG),
        ("8486-1optSL/BIO",             OPTO_EEG_EMG_BIO_SL_CONFIG),
        ("8486-1optSE3/BIO",            OPTO_EEG_3_BIO_SE_CONFIG),
        # OGIM / Opto (rat)
        ("8487-1optSE3",                OPTO_RAT_3EEG_SE_CONFIG),
        ("8487-1optSE4",                OPTO_RAT_4EEG_SE_CONFIG),
        ("8487-1optSE3/BIO",            OPTO_RAT_EEG_3_BIO_SE_CONFIG),
        # Accelerometer
        ("8406-SE3-AXL",                EEG_3_ACCEL_CONFIG),
        ("8406-SL-AXL, 8406-SE-AXL, 8407-SL-AXL", EEG_EMG_ACCEL_CONFIG),
        ("8407-SE-AXL",                 EEG_EMG_RAT_ACCEL_CONFIG),
        ("8407-SE3-AXL",                EEG_3_RAT_ACCEL_CONFIG),
        # Specialty (no ID resistor)
        ("8201-SS",                     EEG_3_8201_SS_CONFIG),
        ("8201-DEP",                    EEG_3_8201_DEP_CONFIG),
    ]

    for raw_models, config in entries:
        for token in raw_models.replace(";", ",").split(","):
            model = token.strip().upper()
            if model and model not in reg:
                reg[model] = config

    return reg


PREAMP_REGISTRY: dict[str, PreampConfig] = _build_registry()


def lookup_preamp_config(model: str) -> PreampConfig | None:
    """Look up a preamp configuration by model number.

    The lookup is case-insensitive and strips surrounding whitespace.
    Returns ``None`` if the model is not found.
    """
    return PREAMP_REGISTRY.get(model.strip().upper())


def list_preamp_models() -> list[str]:
    """Return a sorted list of all registered preamp model numbers."""
    return sorted(PREAMP_REGISTRY.keys())
