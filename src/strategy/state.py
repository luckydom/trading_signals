"""State machine for trade signal generation."""

from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
import pandas as pd
import numpy as np
import json
from pathlib import Path


class PositionState(Enum):
    """Position states for the trading system."""
    NEUTRAL = "neutral"  # No position
    LONG_SPREAD = "long_spread"  # Long ETH, Short BTC
    SHORT_SPREAD = "short_spread"  # Short ETH, Long BTC


class SignalType(Enum):
    """Types of trading signals."""
    ENTER_LONG_SPREAD = "enter_long_spread"
    ENTER_SHORT_SPREAD = "enter_short_spread"
    EXIT_POSITION = "exit_position"
    STOP_LOSS = "stop_loss"
    NO_ACTION = "no_action"


@dataclass
class TradingSignal:
    """Trading signal with metadata."""
    timestamp: datetime
    signal_type: SignalType
    zscore: float
    beta: float
    spread: float
    reason: str
    btc_price: float
    eth_price: float
    previous_state: PositionState
    new_state: PositionState


class TradingStateMachine:
    """
    State machine for generating trading signals based on z-score.

    Entry/Exit logic:
    - Enter long spread when z < -z_in (z crosses below -2)
    - Enter short spread when z > z_in (z crosses above 2)
    - Exit when |z| < z_out (0.5)
    - Stop loss when |z| > z_stop (3.5)
    """

    def __init__(
        self,
        z_in: float = 2.0,
        z_out: float = 0.5,
        z_stop: float = 3.5,
        state_file: Optional[str] = None
    ):
        """
        Initialize trading state machine.

        Args:
            z_in: Entry threshold for z-score
            z_out: Exit threshold for z-score
            z_stop: Stop loss threshold for z-score
            state_file: Path to persist state between runs
        """
        self.z_in = z_in
        self.z_out = z_out
        self.z_stop = z_stop
        self.state_file = Path(state_file) if state_file else None

        # Current state
        self.current_state = PositionState.NEUTRAL
        self.entry_zscore = None
        self.entry_timestamp = None
        self.entry_beta = None

        # Previous z-score for crossing detection
        self.previous_zscore = None

        # Load persisted state
        if self.state_file and self.state_file.exists():
            self.load_state()

    def save_state(self):
        """Persist current state to file."""
        if not self.state_file:
            return

        state_data = {
            'current_state': self.current_state.value,
            'entry_zscore': self.entry_zscore,
            'entry_timestamp': self.entry_timestamp.isoformat() if self.entry_timestamp else None,
            'entry_beta': self.entry_beta,
            'previous_zscore': self.previous_zscore
        }

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(state_data, f, indent=2)

    def load_state(self):
        """Load persisted state from file."""
        if not self.state_file or not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)

            self.current_state = PositionState(state_data.get('current_state', 'neutral'))
            self.entry_zscore = state_data.get('entry_zscore')
            self.entry_timestamp = (
                pd.to_datetime(state_data['entry_timestamp'])
                if state_data.get('entry_timestamp') else None
            )
            self.entry_beta = state_data.get('entry_beta')
            self.previous_zscore = state_data.get('previous_zscore')

            print(f"Loaded state: {self.current_state.value}")
        except Exception as e:
            print(f"Error loading state: {e}")

    def _is_crossing(self, previous: float, current: float, threshold: float, direction: str) -> bool:
        """
        Check if z-score crosses a threshold.

        Args:
            previous: Previous z-score
            current: Current z-score
            threshold: Threshold value
            direction: 'above' or 'below'

        Returns:
            True if crossing detected
        """
        if pd.isna(previous) or pd.isna(current):
            return False

        if direction == 'above':
            return previous <= threshold and current > threshold
        elif direction == 'below':
            return previous >= threshold and current < threshold
        else:
            raise ValueError(f"Invalid direction: {direction}")

    def process_tick(
        self,
        timestamp: datetime,
        zscore: float,
        beta: float,
        spread: float,
        btc_price: float,
        eth_price: float
    ) -> TradingSignal:
        """
        Process a new tick and generate trading signal.

        Args:
            timestamp: Current timestamp
            zscore: Current z-score
            beta: Current hedge ratio
            spread: Current spread value
            btc_price: Current BTC price
            eth_price: Current ETH price

        Returns:
            TradingSignal object
        """
        # Skip if z-score is NaN
        if pd.isna(zscore):
            return TradingSignal(
                timestamp=timestamp,
                signal_type=SignalType.NO_ACTION,
                zscore=zscore,
                beta=beta,
                spread=spread,
                reason="Invalid z-score",
                btc_price=btc_price,
                eth_price=eth_price,
                previous_state=self.current_state,
                new_state=self.current_state
            )

        signal_type = SignalType.NO_ACTION
        reason = ""
        new_state = self.current_state

        # Check for signals based on current state
        if self.current_state == PositionState.NEUTRAL:
            # Check for entry signals (only on crossing)
            if self.previous_zscore is not None:
                if self._is_crossing(self.previous_zscore, zscore, -self.z_in, 'below'):
                    signal_type = SignalType.ENTER_LONG_SPREAD
                    new_state = PositionState.LONG_SPREAD
                    reason = f"Z-score crossed below -{self.z_in:.1f}"
                    self.entry_zscore = zscore
                    self.entry_timestamp = timestamp
                    self.entry_beta = beta

                elif self._is_crossing(self.previous_zscore, zscore, self.z_in, 'above'):
                    signal_type = SignalType.ENTER_SHORT_SPREAD
                    new_state = PositionState.SHORT_SPREAD
                    reason = f"Z-score crossed above {self.z_in:.1f}"
                    self.entry_zscore = zscore
                    self.entry_timestamp = timestamp
                    self.entry_beta = beta

        elif self.current_state == PositionState.LONG_SPREAD:
            # Check for exit conditions
            if abs(zscore) > self.z_stop:
                signal_type = SignalType.STOP_LOSS
                new_state = PositionState.NEUTRAL
                reason = f"Stop loss triggered (|z| > {self.z_stop:.1f})"
                self.entry_zscore = None
                self.entry_timestamp = None
                self.entry_beta = None

            elif abs(zscore) < self.z_out:
                signal_type = SignalType.EXIT_POSITION
                new_state = PositionState.NEUTRAL
                reason = f"Exit signal (|z| < {self.z_out:.1f})"
                self.entry_zscore = None
                self.entry_timestamp = None
                self.entry_beta = None

        elif self.current_state == PositionState.SHORT_SPREAD:
            # Check for exit conditions
            if abs(zscore) > self.z_stop:
                signal_type = SignalType.STOP_LOSS
                new_state = PositionState.NEUTRAL
                reason = f"Stop loss triggered (|z| > {self.z_stop:.1f})"
                self.entry_zscore = None
                self.entry_timestamp = None
                self.entry_beta = None

            elif abs(zscore) < self.z_out:
                signal_type = SignalType.EXIT_POSITION
                new_state = PositionState.NEUTRAL
                reason = f"Exit signal (|z| < {self.z_out:.1f})"
                self.entry_zscore = None
                self.entry_timestamp = None
                self.entry_beta = None

        # Create signal
        signal = TradingSignal(
            timestamp=timestamp,
            signal_type=signal_type,
            zscore=zscore,
            beta=beta,
            spread=spread,
            reason=reason,
            btc_price=btc_price,
            eth_price=eth_price,
            previous_state=self.current_state,
            new_state=new_state
        )

        # Update state
        self.current_state = new_state
        self.previous_zscore = zscore

        # Save state if changed
        if signal_type != SignalType.NO_ACTION:
            self.save_state()

        return signal

    def process_dataframe(self, signals_df: pd.DataFrame) -> List[TradingSignal]:
        """
        Process a DataFrame of signals and generate trading signals.

        Args:
            signals_df: DataFrame with columns: zscore, beta, spread, btc_price, eth_price

        Returns:
            List of TradingSignal objects
        """
        signals = []

        for idx, row in signals_df.iterrows():
            signal = self.process_tick(
                timestamp=idx,
                zscore=row['zscore'],
                beta=row['beta'],
                spread=row['spread'],
                btc_price=row['btc_price'],
                eth_price=row['eth_price']
            )

            if signal.signal_type != SignalType.NO_ACTION:
                signals.append(signal)

        return signals

    def reset(self):
        """Reset state machine to neutral."""
        self.current_state = PositionState.NEUTRAL
        self.entry_zscore = None
        self.entry_timestamp = None
        self.entry_beta = None
        self.previous_zscore = None

        if self.state_file:
            self.save_state()

    def get_position_info(self) -> dict:
        """Get current position information."""
        return {
            'state': self.current_state.value,
            'entry_zscore': self.entry_zscore,
            'entry_timestamp': self.entry_timestamp,
            'entry_beta': self.entry_beta,
            'is_neutral': self.current_state == PositionState.NEUTRAL,
            'is_long_spread': self.current_state == PositionState.LONG_SPREAD,
            'is_short_spread': self.current_state == PositionState.SHORT_SPREAD
        }