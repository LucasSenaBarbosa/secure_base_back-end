"""Execução do NSGA-II (pymoo) sobre o modelo de ``optimization_model``."""

import time
from dataclasses import dataclass
from importlib.metadata import version

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.core.repair import Repair
from pymoo.operators.crossover.pntx import TwoPointCrossover
from pymoo.operators.mutation.bitflip import BitflipMutation
from pymoo.operators.sampling.rnd import BinaryRandomSampling
from pymoo.optimize import minimize
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from modules.service.optimization_model import (
    CompiledLayout,
    constraints,
    is_feasible,
    objectives,
)

CROSSOVER_PROBABILITY = 0.9
LIBRARY = f"pymoo {version('pymoo')}"


@dataclass(frozen=True)
class OptimizationOutcome:
    solutions: list[np.ndarray]
    evaluations: int
    duration_ms: int


class SensorPlacementProblem(Problem):
    """Minimiza (−cobertura, custo, vulnerabilidade) sujeito a orçamento e estoque."""

    def __init__(self, compiled: CompiledLayout):
        super().__init__(
            n_var=compiled.n_genes,
            n_obj=3,
            n_ieq_constr=1 + compiled.n_types,
            xl=0,
            xu=1,
            vtype=bool,
        )
        self.compiled = compiled

    def _evaluate(self, x: np.ndarray, out: dict, *args: object, **kwargs: object) -> None:
        values = objectives(self.compiled, x)
        out["F"] = np.column_stack([-values[:, 0], values[:, 1], values[:, 2]])
        out["G"] = constraints(self.compiled, x)


class OneSensorPerCandidateRepair(Repair):
    """Mantém no máximo um tipo de sensor ativo por ponto candidato.

    Quando crossover ou mutação ativam dois tipos no mesmo ponto, um deles é
    mantido ao acaso. O gerador é semeado pela execução, para reprodutibilidade.
    """

    def __init__(self, compiled: CompiledLayout, seed: int):
        super().__init__()
        self.compiled = compiled
        self.rng = np.random.default_rng(seed)

    def _do(self, problem: Problem, x: np.ndarray, **kwargs: object) -> np.ndarray:
        x = x.astype(bool, copy=True)
        candidates = self.compiled.gene_candidate
        for row in x:
            active = np.flatnonzero(row)
            if active.size < 2:
                continue
            owners, counts = np.unique(candidates[active], return_counts=True)
            for owner in owners[counts > 1]:
                genes = active[candidates[active] == owner]
                keep = self.rng.choice(genes)
                row[genes] = False
                row[keep] = True
        return x


def run_nsga2(
    compiled: CompiledLayout,
    *,
    population_size: int,
    generations: int,
    seed: int,
) -> OptimizationOutcome:
    """Executa o NSGA-II e devolve apenas soluções viáveis e mutuamente não dominadas."""
    started = time.perf_counter()
    algorithm = NSGA2(
        pop_size=population_size,
        sampling=BinaryRandomSampling(),
        crossover=TwoPointCrossover(prob=CROSSOVER_PROBABILITY),
        mutation=BitflipMutation(prob=1.0, prob_var=min(0.5, 1.0 / compiled.n_genes)),
        repair=OneSensorPerCandidateRepair(compiled, seed),
        eliminate_duplicates=True,
    )
    result = minimize(
        SensorPlacementProblem(compiled),
        algorithm,
        ("n_gen", generations),
        seed=seed,
        verbose=False,
    )
    population = np.atleast_2d(result.pop.get("X")).astype(bool)
    return OptimizationOutcome(
        solutions=pareto_front(compiled, population),
        evaluations=int(result.algorithm.evaluator.n_eval),
        duration_ms=round((time.perf_counter() - started) * 1000),
    )


def pareto_front(compiled: CompiledLayout, population: np.ndarray) -> list[np.ndarray]:
    """Filtra viáveis, remove duplicatas e mantém a primeira frente não dominada.

    A viabilidade é recalculada aqui, sem depender do estado interno do pymoo.
    Ordena por custo crescente e, no empate, por cobertura decrescente.
    """
    if population.size == 0:
        return []
    feasible = np.unique(population[is_feasible(compiled, population)], axis=0)
    if feasible.shape[0] == 0:
        return []
    values = objectives(compiled, feasible)
    minimized = np.column_stack([-values[:, 0], values[:, 1], values[:, 2]])
    front = NonDominatedSorting().do(minimized, only_non_dominated_front=True)
    ordered = sorted(front, key=lambda i: (values[i, 1], -values[i, 0], values[i, 2]))
    return [feasible[i] for i in ordered]
