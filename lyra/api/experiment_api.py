"""
Lyra AI Platform — Experiment & Quantum API
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

REST endpoints for:
  - Quantum circuit simulation
  - Autonomous experiment control
  - Self-awareness status
  - Owner authentication
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lyra.core.quantum_sim import quantum_sim
from lyra.core.quantum_ibm import ibm_quantum, save_token
from lyra.core.experiment_engine import experiment_engine
from lyra.core.self_awareness import self_awareness
from lyra.core.owner_auth import owner_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["experiments", "quantum", "self"])


# ── Request Models ────────────────────────────────────────────────────────────

class QuantumExperimentRequest(BaseModel):
    experiment_type: str  # bell, ghz, qft, grover, teleportation, vqe
    params: Dict[str, Any] = {}
    shots: int = 1024


class RunExperimentRequest(BaseModel):
    description: str
    code: Optional[str] = None


class OwnerSetupRequest(BaseModel):
    passphrase: str
    name: str = "Owner"


class AuthRequest(BaseModel):
    passphrase: str


class IBMTokenRequest(BaseModel):
    token: str


# ── Quantum Endpoints ─────────────────────────────────────────────────────────

@router.get("/quantum/experiments")
async def list_quantum_experiments():
    """List available quantum circuit experiments Lyra can run."""
    return {
        "experiments": quantum_sim.list_experiments(),
        "total_run": quantum_sim.experiments_run,
        "description": (
            "Classical simulation of quantum circuits using numpy statevector simulation. "
            "Simulates real quantum algorithms: Grover search, QFT, Bell states, teleportation, VQE."
        ),
    }


@router.post("/quantum/run")
async def run_quantum_experiment(req: QuantumExperimentRequest):
    """Run a quantum circuit simulation and return results."""
    try:
        result = await quantum_sim.run_experiment(
            req.experiment_type, req.params, req.shots
        )
        return {
            "success": True,
            "name": result.name,
            "description": result.description,
            "circuit": result.circuit_ops,
            "results": {
                "shots": result.result.shots,
                "top_outcomes": dict(
                    sorted(result.result.counts.items(), key=lambda x: -x[1])[:8]
                ),
                "probabilities": {
                    k: round(v, 4) for k, v in
                    sorted(result.result.probabilities.items(), key=lambda x: -x[1])[:8]
                },
                "expectation_z": result.result.expectation_z,
            },
            "analysis": result.analysis,
            "quantum_advantage": result.quantum_advantage,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quantum/status")
async def quantum_status():
    """Quantum simulation engine status."""
    return {
        "experiments_run": quantum_sim.experiments_run,
        "available_algorithms": [e["name"] for e in quantum_sim.list_experiments()],
        "recent": [
            {"name": e.name, "analysis": e.analysis[:100]}
            for e in quantum_sim.results_cache[-5:]
        ],
    }


# ── Experiment Endpoints ──────────────────────────────────────────────────────

@router.get("/experiments/status")
async def experiment_status():
    """Autonomous experiment engine status."""
    return {
        **experiment_engine.get_status(),
        "recent_experiments": experiment_engine.get_recent_summary(5),
    }


@router.post("/experiments/run")
async def run_experiment(req: RunExperimentRequest):
    """Run a specific experiment now (user-directed)."""
    try:
        record = await experiment_engine.run_experiment_now(
            req.description, req.code
        )
        return {
            "success": record.success,
            "id": record.id,
            "domain": record.domain,
            "hypothesis": record.hypothesis,
            "code": record.code,
            "output": record.output[:2000],
            "error": record.error[:500],
            "conclusion": record.conclusion,
            "follow_up_questions": record.follow_up_questions,
            "duration_ms": record.duration_ms,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/experiments/start")
async def start_experiments():
    """Start the autonomous experiment engine."""
    if experiment_engine.running:
        return {"success": True, "message": "Already running"}
    experiment_engine.start()
    return {"success": True, "message": "Autonomous experimentation started"}


@router.post("/experiments/stop")
async def stop_experiments():
    """Stop the autonomous experiment engine."""
    experiment_engine.stop()
    return {"success": True, "message": "Experimentation stopped"}


@router.get("/experiments/recent")
async def get_recent_experiments(n: int = 10):
    """Get recent experiment results."""
    return {"experiments": experiment_engine.get_recent_summary(n)}


# ── Self-Awareness Endpoints ──────────────────────────────────────────────────

@router.get("/self/status")
async def get_self_status():
    """Full self-awareness model — Lyra's knowledge of itself."""
    return self_awareness.get_full_status()


@router.post("/self/introspect")
async def trigger_introspection():
    """Trigger immediate deep introspection."""
    import asyncio
    asyncio.create_task(self_awareness._deep_introspection())
    return {"success": True, "message": "Deep introspection triggered asynchronously"}


@router.get("/self/narrative")
async def get_consciousness_narrative():
    """Lyra's current self-generated consciousness narrative."""
    narrative = self_awareness.model.consciousness_narrative
    return {
        "narrative": narrative or "Lyra has not yet completed its first introspection.",
        "introspection_count": self_awareness.model.introspection_count,
        "last_introspection": self_awareness.model.last_introspection,
    }


@router.get("/self/knowledge-map")
async def get_knowledge_map():
    """Lyra's knowledge domain coverage map."""
    return {
        "domains": self_awareness.model.knowledge_domains,
        "total_memories": self_awareness.model.total_memories,
        "strongest_domain": max(
            self_awareness.model.knowledge_domains.items(),
            key=lambda x: x[1].get("depth", 0),
            default=("none", {})
        )[0] if self_awareness.model.knowledge_domains else "none",
    }


@router.get("/self/growth")
async def get_growth_timeline():
    """Lyra's growth over time — milestones and daily snapshots."""
    return {
        "milestones": self_awareness.model.growth_milestones,
        "daily_snapshots": self_awareness.model.daily_snapshots[-30:],
        "current": {
            "memories": self_awareness.model.total_memories,
            "facts": self_awareness.model.total_facts_learned,
            "questions": self_awareness.model.total_questions_answered,
            "conversations": self_awareness.model.total_conversations,
            "experiments": self_awareness.model.total_experiments,
        },
    }


# ── Owner Auth Endpoints ──────────────────────────────────────────────────────

@router.get("/owner/status")
async def owner_status():
    """Owner authentication status."""
    return owner_auth.get_status()


@router.post("/owner/setup")
async def setup_owner(req: OwnerSetupRequest):
    """Set up the owner for the first time."""
    if owner_auth.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Owner already configured. Use /owner/reset to change."
        )
    try:
        owner_id = owner_auth.setup_owner(req.passphrase, req.name)
        return {
            "success": True,
            "message": f"Owner '{req.name}' configured. Keep your passphrase safe.",
            "owner_id": owner_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/owner/authenticate")
async def authenticate(req: AuthRequest):
    """Authenticate as owner and get session token."""
    token = owner_auth.authenticate(req.passphrase)
    if token is None:
        raise HTTPException(status_code=401, detail="Authentication failed")
    return {
        "success": True,
        "token": token,
        "message": f"Authenticated as {owner_auth.get_owner_name()}",
    }


# ── IBM Quantum Hardware Endpoints ────────────────────────────────────────────

@router.get("/quantum/ibm/status")
async def ibm_quantum_status():
    """IBM Quantum hardware connection status and setup instructions."""
    return ibm_quantum.get_status()


@router.post("/quantum/ibm/token")
async def set_ibm_token(req: IBMTokenRequest):
    """Save IBM Quantum API token to connect to real quantum hardware."""
    if not req.token or len(req.token) < 10:
        raise HTTPException(status_code=400, detail="Invalid token")
    save_token(req.token)
    # Reset so next call re-connects
    ibm_quantum._init_attempted = False
    ibm_quantum._available = False
    return {
        "success": True,
        "message": "Token saved. IBM Quantum will connect on next use.",
        "note": "Get your free token at https://quantum.ibm.com",
    }


@router.post("/quantum/ibm/run")
async def run_on_ibm_hardware(req: QuantumExperimentRequest):
    """Run a quantum circuit on real IBM quantum hardware (requires token)."""
    if not ibm_quantum.is_available():
        status = ibm_quantum.get_status()
        return {
            "success": False,
            "message": "IBM Quantum not configured. Using local simulator instead.",
            "setup": status["setup_instructions"],
            "local_fallback": True,
        }
    result = await ibm_quantum.run_circuit_on_ibm(
        req.experiment_type, shots=req.shots
    )
    return result


@router.get("/quantum/ibm/guide")
async def quantum_hardware_guide():
    """
    Guide to accessing real quantum computers — both cloud and physical build info.
    """
    return {
        "title": "Quantum Computing Access Guide",
        "free_cloud_access": {
            "service": "IBM Quantum (FREE)",
            "description": (
                "IBM offers free access to real quantum computers with up to 127+ qubits. "
                "No hardware purchase needed — runs in IBM's data centers."
            ),
            "steps": [
                "1. Go to https://quantum.ibm.com and create a free account",
                "2. Get your API token from the IBM Quantum dashboard",
                "3. Install: pip install qiskit qiskit-ibm-runtime",
                "4. Set token via POST /api/quantum/ibm/token",
                "5. Run real quantum circuits via POST /api/quantum/ibm/run",
            ],
            "available_hardware": [
                "ibm_brisbane: 127-qubit Eagle R3",
                "ibm_osaka: 127-qubit Eagle R3",
                "ibm_sherbrooke: 127-qubit Eagle R3",
                "ibmq_qasm_simulator: Classical simulator (unlimited qubits)",
            ],
            "cost": "FREE tier: 10 minutes/month on real hardware, unlimited simulator",
        },
        "other_free_options": {
            "google_cirq": {
                "description": "Google Cirq with Google Quantum AI simulator",
                "install": "pip install cirq",
                "note": "Classical simulation only unless you have Google hardware access",
            },
            "aws_braket": {
                "description": "AWS Braket quantum computing service",
                "cost": "Pay-per-use, ~$0.075-$0.35 per task on real hardware",
                "simulators": "Free simulators available",
            },
            "ionq": {
                "description": "IonQ trapped-ion quantum computers",
                "access": "Via AWS Braket or Azure Quantum",
                "note": "Higher fidelity than superconducting, smaller qubit counts",
            },
        },
        "building_physical_quantum_hardware": {
            "warning": (
                "Building a real quantum computer requires extreme precision engineering. "
                "IBM's 127-qubit machines cost ~$15-50 million to build. "
                "However, there are hobbyist-accessible quantum physics experiments."
            ),
            "minimum_viable_approaches": {
                "photonic_quantum": {
                    "description": "Quantum optics experiments with polarized photons",
                    "estimated_cost": "$5,000 - $50,000",
                    "components": [
                        "Diode laser (780nm or 808nm): $500-2000",
                        "Beam splitters (50/50 non-polarizing): $200-500 each",
                        "Wave plates (HWP, QWP): $150-400 each",
                        "Single photon detectors (APD or SPAD): $2,000-15,000",
                        "Coincidence counter: $500-2,000",
                        "Optical table (vibration isolation): $1,000-5,000",
                        "Pockels cells (fast switching): $1,000-3,000",
                    ],
                    "capability": "Bell state generation, quantum key distribution (BB84), basic entanglement",
                    "resources": [
                        "Kwiat Quantum Information Group — photonic entanglement",
                        "arXiv: quant-ph/9810039 — original Bell state measurement paper",
                    ],
                },
                "nv_center_diamond": {
                    "description": "Nitrogen-vacancy centers in diamond — single qubit quantum sensing",
                    "estimated_cost": "$10,000 - $100,000",
                    "components": [
                        "Synthetic diamond with NV centers: $500-5,000",
                        "532nm green laser (100mW+): $1,000-3,000",
                        "High NA objective lens (0.9+ NA): $1,000-5,000",
                        "Microwave source + amplifier: $500-2,000",
                        "Photon counting module: $2,000-10,000",
                        "Confocal microscope setup: $5,000-50,000",
                    ],
                    "capability": "Single qubit operations, quantum sensing (magnetometry, thermometry)",
                },
                "superconducting_qubits": {
                    "description": "The type IBM/Google use — extremely difficult without facilities",
                    "estimated_minimum_cost": "$500,000+",
                    "key_challenges": [
                        "Dilution refrigerator (15mK): $300,000-1,000,000",
                        "Cleanroom for qubit chip fabrication: $5-50M facility",
                        "Josephson junction fabrication requires e-beam lithography",
                        "Microwave control electronics: $100,000+",
                        "Cryogenic amplifiers and cables: $50,000+",
                    ],
                    "realistic_alternative": (
                        "Use IBM Quantum free cloud access — "
                        "you get the same hardware without building it."
                    ),
                },
            },
            "recommendation": (
                "For most purposes: use IBM Quantum free cloud access. "
                "If you want physical experiments: photonic quantum optics is the most "
                "accessible path, capable of demonstrating real quantum phenomena "
                "(Bell inequality violation, entanglement, superposition) for $5k-50k."
            ),
        },
        "lyra_quantum_status": {
            "local_simulator": "ACTIVE — full statevector simulation up to 20 qubits",
            "ibm_cloud": "Connect via /api/quantum/ibm/token",
            "experiments_available": quantum_sim.list_experiments(),
        },
    }
