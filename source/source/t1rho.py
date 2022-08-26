# This code is part of Qiskit.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""
T1rho Experiment class.
"""

from typing import Optional, List, Union

import numpy as np
import math

from qiskit.providers.backend import Backend
from qiskit.visualization import *
from ibm_quantum_widgets import *
from qiskit.exceptions import QiskitError
from qiskit.test.mock import FakeBackend
from qiskit import pulse
from qiskit.circuit import QuantumCircuit
from qiskit_experiments.framework import BaseExperiment, Options

from .utils import get_closest_multiple_of
from .utils import play_chunked_gaussian_square
from .t1rho_analysis import T1rhoAnalysis


class T1rho(BaseExperiment):
    r"""
    T1rho experiment class

    # section: overview

        Design and analyze experiments for estimating T\ :sub: `1rho` of the qubit.

        See `Qiskit Textbook <https://qiskit.org/textbook/ch-quantum-hardware/
        calibrating-qubits-pulse.html>`_  for a more detailed explanation on
        these properties.

        Each experiment consists of the following steps:

        1. Circuits generation: This experiment consists of a series of circuits of the form
           .. parsed-literal::
                    ┌─────────┐┌─────────────────┐┌────────┐┌─┐
               q_0: ┤ Rx(π/2) ├┤ SPIN-LOCKING(t) ├┤ RX(π/2)├┤M├
                    └─────────┘└─────────────────┘└────────┘└╥┘
               c: 1/═════════════════════════════════════════╩═
                                                             0
           for each *t* from the specified duration times
           and the durations are specified by the user.
           The durations that are specified are durations for each spin-locking pulse.
           The circuits are run on the device or on a simulator backend.
        2. Backend execution: actually running the circuits on the device (or simulator).
        3. Analysis of results: deduction of T\ :sub:`1`\ , based on the outcomes, by fitting to an exponential curve.

        TODO: need reference? yes, look back here after everything works and is written, is in contributino guide.

    """

    def _default_experiment_options(cls) -> Options:
        """Default experiment options.
        Experiment Options:
            durations (Iterable[float]): Duration times of the spin-locking pulses.
            pi_amplitude (float): Amplitude of the drive for a Gaussian pi pulse.
            drive_chan (PulseChannel): Channel that pulse will play on.
            qubit_freq (float): Frequency of qubit being measured.
        """
        options = super()._default_experiment_options()
        options.pi_amplitude = 0.0
        options.durations = None
        options.drive_chan = None
        options.qubit_freq = 0.0
        options.pi_over_2_sigma_sec = 0.0
        options.pi_over_2_pulse = None
        return options

    def __init__(
        self,
        qubit: int,
        pi_amplitude: float,
        pi_over_2_sigma_sec: float,  # This determines the actual width of the gaussian
        pi_over_2_pulse: pulse,  # TODO: note sure if we pass this in here or if this is the right type
        durations: Union[List[float], np.array],
        backend: Optional[Backend] = None,
        **kwargs,
    ):

        """
        Initialize the T1 experiment class

        Args:
            qubit: the qubit whose T1rho is to be estimated
            durations: duration times of the pulses in seconds
            backend: Optional, the backend to run the experiment on.

        Raises: TODO: figure out what error to raise
            ValueError: if the number of delays is smaller than 3
        """

        self.qubit = qubit

        # Initialize base experiment
        super().__init__(
            qubits=[qubit], analysis=T1rhoAnalysis(), backend=backend
        )  # TODO: figure out analysis class

        # Set experiment options
        self.set_experiment_options(
            durations=durations,
            pi_amplitude=pi_amplitude,  # TODO: switch this to just arbitrary spin-locking_amplitude?
            pi_over_2_pulse=pi_over_2_pulse,
            pi_over_2_sigma_sec=pi_over_2_sigma_sec,
            drive_chan=pulse.DriveChannel(qubit),
            **kwargs,
        )
        self._verify_parameters()  # TODO: this ensures that the inputs are sensible, built in test.

    def _verify_parameters(self):
        # TODO: determine all of the tests we should have here
        # need to have checks that durations are within bounds that can be supported by computers
        """
        Verify input correctness, raise QiskitError if needed.

        Raises:
            QiskitError : Error for invalid input.
        """
        if any(duration < 0 for duration in self.experiment_options.durations):
            raise QiskitError(
                f"The lengths list {self.experiment_options.durations} should only contain "
                "non-negative elements."
            )

    def _set_backend(self, backend: Backend):
        super()._set_backend(backend)

        if not self._backend.configuration().simulator and not isinstance(backend, FakeBackend):
            timing_constraints = getattr(self.transpile_options, "timing_constraints", {})
            if "acquire_alignment" not in timing_constraints:
                timing_constraints["acquire_alignment"] = 16
            scheduling_method = getattr(self.transpile_options, "scheduling_method", "alap")
            self.set_transpile_options(
                timing_constraints=timing_constraints, scheduling_method=scheduling_method
            )

        try:
            qubit_freq = backend.defaults().qubit_freq_est[self.physical_qubits[self.qubit]]
        except (AttributeError, IndexError):
            qubit_freq = self.experiment_options.qubit_freq

        self.set_experiment_options(qubit_freq=qubit_freq)

    def circuits(self) -> List[QuantumCircuit]:
        """
        Return a list of experiment circuits.

        Each circuit consists of RX(π/2) followed by a spin-locking gate and
        then RX(π/2) to put in Z-basis for measurement.

        Returns:
            The experiment circuits.
        """

        opt = self.experiment_options

        # Drive pulse parameters (us = microseconds)
        pi_over_2_duration_sec = (
            opt.pi_over_2_sigma_sec * 8
        )  # This is a truncating parameter, because gaussians don't have a natural finite length
        spin_locking_pulses_qubit = []

        for i in range(len(opt.durations)):
            with pulse.build(self.backend) as spin_locking_pulse_qubit:
                drive_duration = get_closest_multiple_of(
                    pulse.seconds_to_samples(opt.durations[i]), 16
                )
                drive_sigma = pulse.seconds_to_samples(opt.pi_over_2_sigma_sec)
                pulse.shift_phase(math.pi / 2, opt.drive_chan)
                risefall_sigma_ratio = get_closest_multiple_of(
                    pulse.seconds_to_samples(pi_over_2_duration_sec), 16
                ) / (2 * drive_sigma)
                play_chunked_gaussian_square(
                    drive_duration,
                    opt.pi_amplitude,
                    drive_sigma,
                    risefall_sigma_ratio,
                    opt.drive_chan,
                )
                pulse.shift_phase(-math.pi / 2, opt.drive_chan)
            spin_locking_pulses_qubit.append(spin_locking_pulse_qubit)

        circuits = []
        for i in range(len(opt.durations)):

            qc_t1rho = QuantumCircuit(1, 1)

            # TODO: fix naming convention of x?
            qc_t1rho.h(0)
            qc_t1rho.x(0)
            qc_t1rho.h(0)
            qc_t1rho.measure(0, 0)

            # TODO: in the T1 case, they don't calibrate the h pulse (x in their case); but i dont know how the gates are implemented as pulses (probably drag), and im not sure this will act the same way with the spin locking pulse
            #       the problem here is that this experiment is not self-contained. it requires the pi_pulse to be calibrated beforehand
            qc_t1rho.add_calibration("h", (0,), opt.pi_over_2_pulse)
            qc_t1rho.add_calibration("x", (0,), spin_locking_pulses_qubit[i])

            qc_t1rho.metadata = {
                "experiment_type": self._type,
                "qubit": self.physical_qubits[0],
                "xval": opt.durations[i],
                "unit": "s",
            }

            circuits.append(qc_t1rho)

        return circuits

    def _metadata(self):
        metadata = super()._metadata()
        # Store measurement level and meas return if they have been
        # set for the experiment
        for run_opt in ["meas_level", "meas_return"]:
            if hasattr(self.run_options, run_opt):
                metadata[run_opt] = getattr(self.run_options, run_opt)
        return metadata
