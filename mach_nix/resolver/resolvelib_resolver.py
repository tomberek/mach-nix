from typing import Iterable, List

import resolvelib

from mach_nix.data.nixpkgs import NixpkgsIndex
from mach_nix.data.providers import DependencyProviderBase, Candidate
from mach_nix.deptree import remove_circles_and_print
from mach_nix.requirements import Requirement, filter_versions
from mach_nix.resolver import Resolver, ResolvedPkg


# Implement logic so the resolver understands the requirement format.
class Provider(resolvelib.providers.AbstractProvider):
    def __init__(self, nixpkgs: NixpkgsIndex, deps_db: DependencyProviderBase):
        self.nixpkgs = nixpkgs
        self.provider = deps_db

    def get_extras_for(self, dependency):
        # return selected extras
        return tuple(sorted(dependency.selected_extras))

    def get_base_requirement(self, candidate):
        return Requirement("{}=={}".format(candidate.name, candidate.ver))

    def identify(self, requirement_or_candidate):
        return requirement_or_candidate.name

    def get_preference(
        self, identifier, resolutions, candidates, information, backtrack_causes
    ):
        # This logic could be improved, for example to prefer the cause of backtracking.
        # See https://github.com/pypa/pip/blob/main/src/pip/_internal/resolution/resolvelib/provider.py
        # for the implementation in pip.
        return sum(1 for _ in candidates[identifier])

    def find_matches(self, identifier, requirements, incompatibilities):
        return [
            candidate
            for candidate in self.provider.find_matches(list(requirements[identifier]))
            if candidate not in incompatibilities.get(identifier, ())
        ]

    def is_satisfied_by(self, requirement, candidate: Candidate):
        res = bool(len(list(filter_versions([candidate.ver], requirement))))
        return res

    def get_dependencies(self, candidate):
        install_requires, setup_requires = self.provider.get_pkg_reqs(candidate)
        if install_requires is None:
            install_requires = []
        if setup_requires is None:
            setup_requires = []
        deps = install_requires + setup_requires
        return deps


class ResolvelibResolver(Resolver):
    def __init__(self, nixpkgs: NixpkgsIndex, deps_provider: DependencyProviderBase):
        self.nixpkgs = nixpkgs
        self.deps_provider = deps_provider

    def resolve(self, reqs: Iterable[Requirement]) -> List[ResolvedPkg]:
        reporter = resolvelib.BaseReporter()
        result = resolvelib.Resolver(Provider(self.nixpkgs, self.deps_provider), reporter).resolve(reqs, max_rounds=1000)
        nix_py_pkgs = []
        for name in result.graph._forwards.keys():
            if name is None or name.startswith('-'):
                continue
            candidate = result.mapping[name]
            ver = candidate.ver
            install_requires, setup_requires = self.deps_provider.get_pkg_reqs(candidate)
            build_inputs, prop_build_inputs = None, None
            if install_requires is not None:
                prop_build_inputs = list(filter(
                    lambda name: not name.startswith('-'),
                    list({req.key for req in install_requires})))
            if setup_requires is not None:
                build_inputs = list(filter(
                    lambda name: not name.startswith('-'),
                    list({req.key for req in setup_requires})))
            is_root = name in result.graph._forwards[None]
            nix_py_pkgs.append(ResolvedPkg(
                name=name,
                ver=ver,
                raw_version=candidate.raw_version,
                build_inputs=build_inputs,
                prop_build_inputs=prop_build_inputs,
                is_root=is_root,
                provider_info=candidate.provider_info,
                extras_selected=list(result.mapping[name].selected_extras),
                build=candidate.build
            ))
        remove_circles_and_print(nix_py_pkgs, self.nixpkgs)
        return nix_py_pkgs
