# Copyright 2016 Autodesk Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pyccc
from moldesign import units as u
from moldesign import compute
from moldesign.interfaces.openmm import OpenMMPickleMixin, force_remote, MdtReporter, pint2simtk, mm

from .base import IntegratorBase, LangevinBase


def exports(o):
    __all__.append(o.__name__)
    return o
__all__ = []


class OpenMMBaseIntegrator(IntegratorBase, OpenMMPickleMixin):
    _openmm_compatible = True

    def prep(self):
        assert self.mol.energy_model._openmm_compatible
        if self._prepped and self.model is self.mol.energy_model and self.model._prepped: return
        self.model = self.mol.energy_model
        self.model.prep()
        self.sim = self.model.sim
        self.reporter = self._attach_reporters()
        self._prepped = True

    def run(self, run_for, wait=False):
        # TODO: like model.minimize, this is a hacky wrapper that we need to replace with
        # something more generalizable
        try:
            traj = self._run(run_for)
        except pyccc.ProgramFailure:
            raise pyccc.ProgramFailure('OpenMM crashed silently. Please examine the output. '
                                       'This may be due to large forces from, for example, '
                                       'an insufficiently minimized starting geometry.')
        if force_remote or (not wait):
            self.mol.energy_model._sync_remote(traj.mol)
            traj.mol = self.mol
        return traj

    @compute.runsremotely(remote=force_remote, is_imethod=True)
    def _run(self, run_for):
        self.prep()
        nsteps = self.time_to_steps(run_for, self.params.timestep)
        self.mol.time = 0.0 * u.default.time
        self.model._set_openmm_state()
        self.reporter.annotation = 'Langevin dynamics @ %s' % self.params.temperature
        self.reporter.report_from_mol()
        self.sim.step(nsteps)
        if self.reporter.last_report_time != self.mol.time:
            self.reporter.report_from_mol()
        self.reporter.report_from_mol()
        self.model._sync_to_openmm()
        return self.reporter.trajectory

    def _attach_reporters(self):
        """
        Make sure the simulation has reporters for this run
        :return:
        """
        report_interval = self.time_to_steps(self.params.frame_interval,
                                             self.params.timestep)
        reporter = MdtReporter(self.mol, report_interval)
        self.sim.reporters = [reporter]
        return reporter


@exports
class OpenMMVerlet(OpenMMBaseIntegrator):
    def get_openmm_integrator(self):
        integrator = mm.VerletIntegrator(pint2simtk(self.params.timestep))
        return integrator


@exports
class OpenMMLangevin(LangevinBase, OpenMMBaseIntegrator):
    def get_openmm_integrator(self):
        integrator = mm.LangevinIntegrator(
            pint2simtk(self.params.temperature),
            pint2simtk(self.params.collision_rate),
            pint2simtk(self.params.timestep))
        return integrator

