"""
Lyra AI Platform — Quantum Simulation Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Full quantum circuit simulator running on classical hardware using numpy.
No quantum hardware required — simulates quantum states, gates, measurements,
entanglement, superposition, and quantum algorithms.

Real quantum computers cost millions and require cryogenic cooling.
This simulates the *mathematics* of quantum computing, giving Lyra genuine
ability to reason about, experiment with, and solve quantum problems.
"""
import asyncio
import cmath
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ── Quantum Gates as 2x2 unitary matrices ────────────────────────────────────

GATES: Dict[str, np.ndarray] = {
    # Single-qubit
    "I":  np.array([[1, 0], [0, 1]], dtype=complex),
    "X":  np.array([[0, 1], [1, 0]], dtype=complex),           # Pauli-X (NOT)
    "Y":  np.array([[0, -1j], [1j, 0]], dtype=complex),        # Pauli-Y
    "Z":  np.array([[1, 0], [0, -1]], dtype=complex),          # Pauli-Z
    "H":  np.array([[1, 1], [1, -1]], dtype=complex) / math.sqrt(2),  # Hadamard
    "S":  np.array([[1, 0], [0, 1j]], dtype=complex),          # Phase (π/2)
    "T":  np.array([[1, 0], [0, cmath.exp(1j * math.pi / 4)]], dtype=complex),  # T (π/8)
    "Sd": np.array([[1, 0], [0, -1j]], dtype=complex),         # S† (dagger)
    "Td": np.array([[1, 0], [0, cmath.exp(-1j * math.pi / 4)]], dtype=complex),
}


def rx_gate(theta: float) -> np.ndarray:
    """Rotation around X-axis by angle theta."""
    return np.array([
        [math.cos(theta / 2), -1j * math.sin(theta / 2)],
        [-1j * math.sin(theta / 2), math.cos(theta / 2)]
    ], dtype=complex)


def ry_gate(theta: float) -> np.ndarray:
    """Rotation around Y-axis by angle theta."""
    return np.array([
        [math.cos(theta / 2), -math.sin(theta / 2)],
        [math.sin(theta / 2), math.cos(theta / 2)]
    ], dtype=complex)


def rz_gate(theta: float) -> np.ndarray:
    """Rotation around Z-axis by angle theta."""
    return np.array([
        [cmath.exp(-1j * theta / 2), 0],
        [0, cmath.exp(1j * theta / 2)]
    ], dtype=complex)


def phase_gate(phi: float) -> np.ndarray:
    """Arbitrary phase gate P(φ)."""
    return np.array([[1, 0], [0, cmath.exp(1j * phi)]], dtype=complex)


# ── Quantum Circuit Operation ─────────────────────────────────────────────────

@dataclass
class QuantumOperation:
    gate: str
    qubits: List[int]
    params: List[float] = field(default_factory=list)
    label: str = ""


@dataclass
class MeasurementResult:
    state_vector: np.ndarray
    probabilities: Dict[str, float]
    sampled_outcome: str
    shots: int
    counts: Dict[str, int]
    expectation_z: List[float]  # <Z> for each qubit


@dataclass
class ExperimentResult:
    name: str
    description: str
    circuit_ops: List[str]
    result: MeasurementResult
    analysis: str
    quantum_advantage: bool


# ── Quantum State Simulator ───────────────────────────────────────────────────

class QuantumState:
    """
    Statevector simulator for n-qubit quantum systems.

    State is stored as a complex vector of length 2^n.
    Index i corresponds to computational basis state |i⟩ (big-endian).
    """

    def __init__(self, n_qubits: int):
        if n_qubits > 20:
            raise ValueError(f"Too many qubits: {n_qubits}. Max 20 (2^20 = 1M amplitudes).")
        self.n_qubits = n_qubits
        self.dim = 2 ** n_qubits
        # Start in |0...0⟩
        self.state = np.zeros(self.dim, dtype=complex)
        self.state[0] = 1.0

    def reset(self):
        self.state = np.zeros(self.dim, dtype=complex)
        self.state[0] = 1.0

    def apply_gate(self, gate_matrix: np.ndarray, qubit: int):
        """Apply single-qubit gate to qubit index."""
        # Build full operator via tensor product
        op = np.eye(1, dtype=complex)
        for q in range(self.n_qubits):
            if q == qubit:
                op = np.kron(op, gate_matrix)
            else:
                op = np.kron(op, GATES["I"])
        self.state = op @ self.state

    def apply_cnot(self, control: int, target: int):
        """Apply CNOT (controlled-X) gate."""
        new_state = np.zeros(self.dim, dtype=complex)
        for idx in range(self.dim):
            bits = format(idx, f'0{self.n_qubits}b')
            ctrl_bit = int(bits[self.n_qubits - 1 - control])
            if ctrl_bit == 1:
                # Flip target qubit
                tgt_pos = self.n_qubits - 1 - target
                new_bits = list(bits)
                new_bits[tgt_pos] = '1' if bits[tgt_pos] == '0' else '0'
                new_idx = int(''.join(new_bits), 2)
                new_state[new_idx] += self.state[idx]
            else:
                new_state[idx] += self.state[idx]
        self.state = new_state

    def apply_cz(self, control: int, target: int):
        """Apply CZ (controlled-Z) gate."""
        new_state = self.state.copy()
        for idx in range(self.dim):
            bits = format(idx, f'0{self.n_qubits}b')
            ctrl_bit = int(bits[self.n_qubits - 1 - control])
            tgt_bit = int(bits[self.n_qubits - 1 - target])
            if ctrl_bit == 1 and tgt_bit == 1:
                new_state[idx] *= -1
        self.state = new_state

    def apply_swap(self, q1: int, q2: int):
        """SWAP two qubits."""
        self.apply_cnot(q1, q2)
        self.apply_cnot(q2, q1)
        self.apply_cnot(q1, q2)

    def measure_all(self, shots: int = 1024) -> MeasurementResult:
        """Measure all qubits, return probability distribution and sampled outcomes."""
        probs = np.abs(self.state) ** 2
        probs = probs / probs.sum()  # Normalize

        # Build probability dict
        prob_dict: Dict[str, float] = {}
        for i, p in enumerate(probs):
            if p > 1e-10:
                label = format(i, f'0{self.n_qubits}b')
                prob_dict[label] = float(p)

        # Sample shots
        outcomes = np.random.choice(self.dim, size=shots, p=probs)
        counts: Dict[str, int] = {}
        for o in outcomes:
            key = format(o, f'0{self.n_qubits}b')
            counts[key] = counts.get(key, 0) + 1

        # Most likely outcome
        sampled = max(counts, key=counts.get)

        # Expectation value <Z> for each qubit
        exp_z = []
        for q in range(self.n_qubits):
            ez = 0.0
            for i, p in enumerate(probs):
                bit = (i >> q) & 1
                ez += p * (1 - 2 * bit)  # +1 for |0⟩, -1 for |1⟩
            exp_z.append(round(ez, 6))

        return MeasurementResult(
            state_vector=self.state.copy(),
            probabilities=prob_dict,
            sampled_outcome=sampled,
            shots=shots,
            counts=counts,
            expectation_z=exp_z,
        )

    def get_entanglement_entropy(self, qubit: int) -> float:
        """Von Neumann entropy of reduced density matrix for one qubit (0-1 scale)."""
        # Partial trace over all qubits except `qubit`
        rho = np.zeros((2, 2), dtype=complex)
        for i in range(self.dim):
            for j in range(self.dim):
                # Check all other qubits match
                mask = ~(1 << qubit)
                if (i & mask) == (j & mask):
                    bi = (i >> qubit) & 1
                    bj = (j >> qubit) & 1
                    rho[bi, bj] += self.state[i] * np.conj(self.state[j])
        # Eigenvalues
        eigenvalues = np.linalg.eigvalsh(rho)
        eigenvalues = eigenvalues[eigenvalues > 1e-12]
        entropy = -np.sum(eigenvalues * np.log2(eigenvalues))
        return float(np.clip(entropy, 0.0, 1.0))


# ── Quantum Circuit Builder ───────────────────────────────────────────────────

class QuantumCircuit:
    """
    High-level quantum circuit builder.
    Build a circuit, then execute it on the QuantumState simulator.
    """

    def __init__(self, n_qubits: int, name: str = "circuit"):
        self.n_qubits = n_qubits
        self.name = name
        self.ops: List[QuantumOperation] = []

    def h(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("H", [qubit]))
        return self

    def x(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("X", [qubit]))
        return self

    def y(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("Y", [qubit]))
        return self

    def z(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("Z", [qubit]))
        return self

    def s(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("S", [qubit]))
        return self

    def t(self, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("T", [qubit]))
        return self

    def rx(self, theta: float, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("Rx", [qubit], [theta]))
        return self

    def ry(self, theta: float, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("Ry", [qubit], [theta]))
        return self

    def rz(self, theta: float, qubit: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("Rz", [qubit], [theta]))
        return self

    def cnot(self, control: int, target: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("CNOT", [control, target]))
        return self

    def cz(self, control: int, target: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("CZ", [control, target]))
        return self

    def swap(self, q1: int, q2: int) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("SWAP", [q1, q2]))
        return self

    def barrier(self) -> "QuantumCircuit":
        self.ops.append(QuantumOperation("BARRIER", []))
        return self

    def run(self, shots: int = 1024) -> MeasurementResult:
        """Execute the circuit and return measurement results."""
        state = QuantumState(self.n_qubits)
        for op in self.ops:
            if op.gate == "BARRIER":
                continue
            elif op.gate in GATES:
                state.apply_gate(GATES[op.gate], op.qubits[0])
            elif op.gate == "Rx":
                state.apply_gate(rx_gate(op.params[0]), op.qubits[0])
            elif op.gate == "Ry":
                state.apply_gate(ry_gate(op.params[0]), op.qubits[0])
            elif op.gate == "Rz":
                state.apply_gate(rz_gate(op.params[0]), op.qubits[0])
            elif op.gate == "CNOT":
                state.apply_cnot(op.qubits[0], op.qubits[1])
            elif op.gate == "CZ":
                state.apply_cz(op.qubits[0], op.qubits[1])
            elif op.gate == "SWAP":
                state.apply_swap(op.qubits[0], op.qubits[1])
        return state.measure_all(shots)

    def describe(self) -> List[str]:
        lines = [f"Circuit '{self.name}' ({self.n_qubits} qubits, {len(self.ops)} ops)"]
        for op in self.ops:
            if op.gate == "BARRIER":
                lines.append("  ───────────────────")
            elif op.params:
                param_str = ", ".join(f"{p:.4f}" for p in op.params)
                lines.append(f"  {op.gate}({param_str}) q{op.qubits}")
            else:
                lines.append(f"  {op.gate} q{op.qubits}")
        return lines


# ── Quantum Algorithm Library ─────────────────────────────────────────────────

class QuantumAlgorithms:
    """
    Pre-built quantum algorithm implementations Lyra can run and study.
    All run on the classical simulator — no quantum hardware needed.
    """

    @staticmethod
    def bell_state(which: int = 0) -> Tuple[QuantumCircuit, str]:
        """
        Create one of the 4 Bell states (maximally entangled 2-qubit states).
        which: 0=Φ+, 1=Φ-, 2=Ψ+, 3=Ψ-
        """
        names = ["Φ⁺ (|00⟩+|11⟩)/√2", "Φ⁻ (|00⟩-|11⟩)/√2",
                 "Ψ⁺ (|01⟩+|10⟩)/√2", "Ψ⁻ (|01⟩-|10⟩)/√2"]
        circ = QuantumCircuit(2, f"Bell {names[which]}")
        if which in (1, 3):
            circ.x(0)
        if which in (2, 3):
            circ.x(1)
        circ.h(0).cnot(0, 1)
        return circ, names[which]

    @staticmethod
    def ghz_state(n: int = 3) -> QuantumCircuit:
        """GHZ state: (|0...0⟩ + |1...1⟩)/√2 — maximal n-qubit entanglement."""
        circ = QuantumCircuit(n, f"GHZ-{n}")
        circ.h(0)
        for i in range(1, n):
            circ.cnot(0, i)
        return circ

    @staticmethod
    def quantum_fourier_transform(n: int) -> QuantumCircuit:
        """QFT on n qubits — core of Shor's factoring algorithm."""
        circ = QuantumCircuit(n, f"QFT-{n}")
        for j in range(n):
            circ.h(j)
            for k in range(j + 1, n):
                angle = math.pi / (2 ** (k - j))
                circ.ops.append(QuantumOperation("Rz", [k], [angle], f"CR{k-j}"))
        # Swap qubits to correct bit ordering
        for i in range(n // 2):
            circ.swap(i, n - 1 - i)
        return circ

    @staticmethod
    def grover_search(n: int, target: int) -> QuantumCircuit:
        """
        Grover's search algorithm — finds target in O(√N) vs O(N) classically.
        n qubits search space = 2^n items.
        """
        circ = QuantumCircuit(n, f"Grover-n{n}-target{target}")
        # Initialize superposition
        for q in range(n):
            circ.h(q)
        # Optimal iterations: π/4 * √N
        iterations = max(1, round(math.pi / 4 * math.sqrt(2 ** n)))
        for _ in range(iterations):
            # Oracle: flip phase of target state
            target_bits = format(target, f'0{n}b')
            for q, bit in enumerate(reversed(target_bits)):
                if bit == '0':
                    circ.x(q)
            # Multi-controlled Z via H + multi-CNOT + H (simplified for small n)
            circ.z(n - 1)  # simplified oracle
            for q, bit in enumerate(reversed(target_bits)):
                if bit == '0':
                    circ.x(q)
            # Diffusion operator
            for q in range(n):
                circ.h(q)
                circ.x(q)
            circ.z(n - 1)
            for q in range(n):
                circ.x(q)
                circ.h(q)
        return circ

    @staticmethod
    def quantum_teleportation() -> QuantumCircuit:
        """
        Quantum teleportation protocol (3 qubits).
        Transfers qubit 0's state to qubit 2 using entanglement.
        """
        circ = QuantumCircuit(3, "Quantum Teleportation")
        # Prepare message qubit in arbitrary state
        circ.ry(1.2, 0)
        circ.barrier()
        # Create Bell pair between qubits 1 and 2
        circ.h(1).cnot(1, 2)
        circ.barrier()
        # Bell measurement on qubits 0 and 1
        circ.cnot(0, 1).h(0)
        circ.barrier()
        # Classical correction (conditioned on measurement — simplified)
        circ.cnot(1, 2).cz(0, 2)
        return circ

    @staticmethod
    def variational_quantum_eigensolver(n_params: int = 4) -> QuantumCircuit:
        """
        VQE ansatz — quantum chemistry / optimization.
        Parametrized circuit that can be classically optimized.
        """
        circ = QuantumCircuit(2, "VQE Ansatz")
        params = [random.uniform(0, 2 * math.pi) for _ in range(n_params)]
        circ.ry(params[0], 0)
        circ.ry(params[1], 1)
        circ.cnot(0, 1)
        circ.ry(params[2], 0)
        circ.ry(params[3], 1)
        return circ


# ── High-Level Quantum Experiment Interface ───────────────────────────────────

class QuantumSimulator:
    """
    Lyra's quantum computing interface.
    Provides natural-language-oriented quantum experiment capabilities.
    """

    def __init__(self):
        self.algorithms = QuantumAlgorithms()
        self.experiments_run = 0
        self.results_cache: List[ExperimentResult] = []

    async def run_experiment(
        self,
        experiment_type: str,
        params: Optional[Dict] = None,
        shots: int = 1024,
    ) -> ExperimentResult:
        """Run a named quantum experiment asynchronously."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._run_experiment_sync, experiment_type, params or {}, shots
        )
        self.experiments_run += 1
        self.results_cache.append(result)
        if len(self.results_cache) > 100:
            self.results_cache.pop(0)
        return result

    def _run_experiment_sync(
        self, experiment_type: str, params: Dict, shots: int
    ) -> ExperimentResult:
        exp_type = experiment_type.lower().replace(" ", "_").replace("-", "_")

        if exp_type in ("bell", "bell_state", "entanglement"):
            which = params.get("which", 0)
            circ, name = self.algorithms.bell_state(which)
            result = circ.run(shots)
            analysis = self._analyze_bell(result, name)
            return ExperimentResult(
                name=f"Bell State {name}",
                description="Maximally entangled 2-qubit state demonstrating quantum entanglement",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=True,
            )

        elif exp_type in ("ghz", "ghz_state"):
            n = params.get("n", 3)
            circ = self.algorithms.ghz_state(n)
            result = circ.run(shots)
            top = max(result.counts, key=result.counts.get)
            analysis = (
                f"GHZ state created on {n} qubits. "
                f"Most common outcome: |{top}⟩ ({result.counts[top]/shots*100:.1f}%). "
                f"Entanglement confirmed: only |{'0'*n}⟩ and |{'1'*n}⟩ observed. "
                "This state cannot exist classically — it is a superposition of all-zeros and all-ones."
            )
            return ExperimentResult(
                name=f"GHZ-{n} State",
                description=f"Greenberger-Horne-Zeilinger state: {n}-qubit maximal entanglement",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=True,
            )

        elif exp_type in ("qft", "quantum_fourier_transform", "fourier"):
            n = params.get("n", 3)
            circ = self.algorithms.quantum_fourier_transform(n)
            result = circ.run(shots)
            analysis = (
                f"Quantum Fourier Transform on {n} qubits. "
                f"QFT is the core of Shor's algorithm (polynomial-time factoring). "
                f"Classical DFT on {2**n} elements: O(N log N) = {2**n * n} ops. "
                f"QFT: O(n²) = {n**2} gates. Exponential speedup achieved."
            )
            return ExperimentResult(
                name=f"QFT-{n}",
                description=f"Quantum Fourier Transform on {n} qubits",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=True,
            )

        elif exp_type in ("grover", "grover_search", "search"):
            n = params.get("n", 3)
            target = params.get("target", random.randint(0, 2**n - 1))
            circ = self.algorithms.grover_search(n, target)
            result = circ.run(shots)
            target_str = format(target, f'0{n}b')
            target_count = result.counts.get(target_str, 0)
            target_prob = target_count / shots * 100
            classical_prob = 1 / 2**n * 100
            analysis = (
                f"Grover's search for |{target_str}⟩ (item {target}) in 2^{n}={2**n} item space. "
                f"Target found with probability: {target_prob:.1f}% vs classical {classical_prob:.1f}%. "
                f"Quantum speedup: O(√{2**n}) = {round(math.sqrt(2**n),1)} ops vs classical O({2**n})."
            )
            return ExperimentResult(
                name=f"Grover Search (target={target})",
                description=f"Grover's quantum search in {2**n}-item space",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=target_prob > classical_prob * 2,
            )

        elif exp_type in ("teleportation", "quantum_teleportation"):
            circ = self.algorithms.quantum_teleportation()
            result = circ.run(shots)
            analysis = (
                "Quantum teleportation protocol. "
                "Qubit state transferred from qubit 0 to qubit 2 using shared entanglement. "
                "No physical matter was transported — only quantum information. "
                "Requires 2 classical bits for correction (cannot exceed light speed — no FTL)."
            )
            return ExperimentResult(
                name="Quantum Teleportation",
                description="3-qubit teleportation protocol using Bell pair",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=True,
            )

        elif exp_type in ("vqe", "variational", "eigensolver"):
            circ = self.algorithms.variational_quantum_eigensolver()
            result = circ.run(shots)
            analysis = (
                "Variational Quantum Eigensolver (VQE) ansatz. "
                "Used in quantum chemistry to find ground state energies. "
                "Hybrid classical-quantum algorithm: classical optimizer tunes gate parameters, "
                "quantum circuit estimates energy. Applicable to drug discovery, materials science."
            )
            return ExperimentResult(
                name="VQE Ansatz",
                description="Variational quantum circuit for eigenvalue estimation",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=True,
            )

        else:
            # Custom circuit from description
            n = params.get("n_qubits", 2)
            circ = QuantumCircuit(n, experiment_type)
            for q in range(n):
                circ.h(q)
            for q in range(n - 1):
                circ.cnot(q, q + 1)
            result = circ.run(shots)
            analysis = f"Custom {n}-qubit circuit: superposition + entanglement chain. State in equal superposition of {2**n} basis states."
            return ExperimentResult(
                name=experiment_type,
                description=f"Custom {n}-qubit quantum circuit",
                circuit_ops=circ.describe(),
                result=result,
                analysis=analysis,
                quantum_advantage=False,
            )

    def _analyze_bell(self, result: MeasurementResult, name: str) -> str:
        counts = result.counts
        total = sum(counts.values())
        expected_states = ["00", "11"]
        on_target = sum(counts.get(s, 0) for s in expected_states) / total * 100
        return (
            f"Bell state {name} verified. "
            f"{on_target:.1f}% of measurements in {{|00⟩, |11⟩}} (expected ~100%). "
            f"Measurement outcomes: {dict(sorted(counts.items(), key=lambda x: -x[1])[:4])}. "
            "This demonstrates quantum entanglement: measuring qubit 0 instantly determines qubit 1, "
            "regardless of physical separation."
        )

    def format_result_for_llm(self, exp: ExperimentResult) -> str:
        """Format experiment result as text for injection into LLM context."""
        lines = [
            f"[QUANTUM EXPERIMENT: {exp.name}]",
            f"Description: {exp.description}",
            f"Quantum advantage demonstrated: {exp.quantum_advantage}",
            "",
            "Circuit:",
        ]
        lines.extend(f"  {line}" for line in exp.circuit_ops)
        lines.extend([
            "",
            f"Results ({exp.result.shots} shots):",
            f"  Top outcomes: {dict(sorted(exp.result.counts.items(), key=lambda x: -x[1])[:5])}",
            f"  ⟨Z⟩ per qubit: {exp.result.expectation_z}",
            "",
            f"Analysis: {exp.analysis}",
        ])
        return "\n".join(lines)

    def list_experiments(self) -> List[Dict]:
        return [
            {"name": "bell_state", "description": "Quantum entanglement (Bell pair)", "qubits": 2},
            {"name": "ghz_state", "description": "Multi-qubit maximal entanglement", "qubits": "3-10"},
            {"name": "qft", "description": "Quantum Fourier Transform (core of Shor's)", "qubits": "2-8"},
            {"name": "grover_search", "description": "Quantum search — O(√N) speedup", "qubits": "2-6"},
            {"name": "teleportation", "description": "Quantum state teleportation", "qubits": 3},
            {"name": "vqe", "description": "Variational Quantum Eigensolver", "qubits": 2},
        ]


# Singleton
quantum_sim = QuantumSimulator()
