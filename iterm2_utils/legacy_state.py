"""Strict historical v1 data. Never discover or invoke a historical agent here."""
import copy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from .models import UiStep
from .state import validate_resources, validate_ui, validate_native_entry

VERSION = '1'
AGENTS = frozenset({'codex', 'claude', 'omp'})
FEATURES = frozenset({'clipboard', 'status', 'notifications', 'restore', 'mcp', 'shell',
                      'shortcuts', 'appearance', 'project-launcher', 'bootstrap-skill'})
SHORTCUTS = frozenset({'ctrl-v-ru', 'alt-enter', 'ctrl-q', 'resume'})


@dataclass
class LegacySelection:
    agents: frozenset[str]
    features: frozenset[str]
    shortcuts: frozenset[str]
    parent_profile: str
    adopt_legacy: bool = False
    agent_features: dict[str, list[str]] | None = None
    agent_shortcuts: dict[str, list[str]] | None = None
    coexist_notifications: bool = False
    notification_coexist_agents: list[str] | None = None

    def coexist_for(self, agent):
        return (agent in self.notification_coexist_agents if self.notification_coexist_agents is not None
                else self.coexist_notifications and agent in self.agents)

    def features_for(self, agent):
        values = self.features if self.agent_features is None else self.agent_features.get(agent, ())
        return frozenset(values) & self.features if agent in self.agents else frozenset()

    def shortcuts_for(self, agent):
        values = self.shortcuts if self.agent_shortcuts is None else self.agent_shortcuts.get(agent, ())
        return frozenset(values) & self.shortcuts if 'shortcuts' in self.features_for(agent) else frozenset()

    def agents_for(self, feature):
        return frozenset(a for a in self.agents if feature in self.features_for(a)
                         and (feature not in {'clipboard', 'restore', 'appearance'} or a == 'codex'))

    @property
    def pairs(self):
        return frozenset(a+':'+f for f in self.features for a in self.agents_for(f))

    def explicit(self):
        from dataclasses import replace
        features = {a: sorted(f for f in self.features_for(a)
                    if f not in {'clipboard', 'restore', 'appearance'} or a == 'codex') for a in self.agents}
        shortcuts = {a: sorted(self.shortcuts_for(a)) for a in self.agents}
        return replace(self, agent_features=features, agent_shortcuts=shortcuts)

    def merge(self, other, features):
        from dataclasses import replace
        own, new = self.explicit(), other.explicit()
        agents = own.agents | new.agents
        pairs = {a: sorted(own.features_for(a) | (new.features_for(a) & features)) for a in agents}
        keys = {a: sorted(own.shortcuts_for(a) | (new.shortcuts_for(a) if 'shortcuts' in features else set())) for a in agents}
        return replace(other, agents=agents, features=frozenset(f for fs in pairs.values() for f in fs),
                       shortcuts=frozenset(k for ks in keys.values() for k in ks),
                       agent_features=pairs, agent_shortcuts=keys,
                       coexist_notifications=self.coexist_notifications or other.coexist_notifications,
                       notification_coexist_agents=sorted(a for a in agents if own.coexist_for(a) or
                           ('notifications' in features and a in new.agents_for('notifications') and new.coexist_for(a))))

    def without(self, features, agents):
        from dataclasses import replace
        own = self.explicit()
        pairs = {a: sorted(own.features_for(a) - (features if a in agents else set())) for a in own.agents}
        keys = {a: sorted(own.shortcuts_for(a)) if 'shortcuts' in pairs[a] else [] for a in own.agents}
        return replace(own, features=frozenset(f for fs in pairs.values() for f in fs),
                       shortcuts=frozenset(k for ks in keys.values() for k in ks),
                       agent_features=pairs, agent_shortcuts=keys,
                       notification_coexist_agents=sorted(a for a in own.agents if own.coexist_for(a) and 'notifications' in pairs[a]))


@dataclass
class LegacyPaths:
    home: Path
    zshrc: Path
    codex_home: Path
    claude_settings: Path
    config: Path
    cache: Path
    data: Path
    profiles: Path
    repo: Path


@dataclass
class LegacyReceipt:
    version: str
    selection: LegacySelection
    resources: list[dict]
    pending_ui: list[UiStep]
    ui_snapshots: dict[str, list[dict]] = field(default_factory=dict)


def validate(receipt):
    if not isinstance(receipt, LegacyReceipt) or not isinstance(receipt.selection, LegacySelection):
        raise ValueError('Historical receipt required')
    choice = receipt.selection
    if (not isinstance(choice.agents, frozenset) or not choice.agents <= AGENTS or
            not isinstance(choice.features, frozenset) or not choice.features <= FEATURES or
            not isinstance(choice.shortcuts, frozenset) or not choice.shortcuts <= SHORTCUTS):
        raise ValueError('Unknown historical selection')
    if 'omp' in choice.agents and choice.features - {'bootstrap-skill'}:
        raise ValueError('Historical omp receipts are bootstrap-only')
    if not isinstance(choice.parent_profile, str) or type(choice.adopt_legacy) is not bool or type(choice.coexist_notifications) is not bool:
        raise ValueError('Invalid selection')
    if choice.notification_coexist_agents is not None and (not isinstance(choice.notification_coexist_agents, list) or
            any(not isinstance(a,str) or a not in choice.agents for a in choice.notification_coexist_agents)):
        raise ValueError('Invalid coexistence choice')
    if (choice.agent_features is None) != (choice.agent_shortcuts is None):
        raise ValueError('Incomplete pairwise selection')
    if choice.agent_features is not None:
        for mapping, allowed in ((choice.agent_features, choice.features), (choice.agent_shortcuts, choice.shortcuts)):
            if not isinstance(mapping, dict) or set(mapping) != set(choice.agents):
                raise ValueError('Invalid pairwise agents')
            for agent, values in mapping.items():
                if not isinstance(values, list) or any(not isinstance(v,str) for v in values) or len(set(values)) != len(values) or not set(values) <= allowed:
                    raise ValueError('Invalid pairwise choices')
            if set().union(*(set(values) for values in mapping.values())) != set(allowed):
                raise ValueError('Pairwise choices disagree with aggregate')
        if any(choice.agent_shortcuts[a] and 'shortcuts' not in choice.agent_features[a] for a in choice.agents):
            raise ValueError('Shortcut choices require their feature')
    if receipt.version != VERSION or not isinstance(receipt.resources,list):
        raise ValueError('Unsupported receipt')
    if not isinstance(receipt.ui_snapshots, dict) or set(receipt.ui_snapshots) - {'claude-native-status'}:
        raise ValueError('Invalid UI snapshot')
    for entries in receipt.ui_snapshots.values():
        if not isinstance(entries, list):
            raise ValueError('Invalid UI snapshot')
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'event', 'entry'} or not isinstance(entry['event'], str):
                raise ValueError('Invalid UI snapshot entry')
            validate_native_entry(entry)
    validate_resources(receipt.resources)
    validate_ui(receipt.pending_ui)
    if any(step.agent not in AGENTS | {None} or step.feature not in FEATURES for step in receipt.pending_ui):
        raise ValueError('Unknown historical UI choice')
    for resource in receipt.resources:
        for owner in resource['owners']:
            if owner.startswith('shared:'):
                if owner not in {'shared:runtime', 'shared:shell', 'shared:hooks', 'shared:codex-hooks',
                                 'shared:agent-profiles', 'shared:project-launcher'}:
                    raise ValueError('Unknown historical owner')
            elif ':' in owner:
                agent, feature = owner.split(':', 1)
                if agent not in AGENTS or feature not in FEATURES or (agent == 'omp' and feature != 'bootstrap-skill'):
                    raise ValueError('Unknown historical owner')
            elif owner not in FEATURES:
                raise ValueError('Unknown historical owner')
    return receipt


def decode(raw: dict) -> LegacyReceipt:
    if not isinstance(raw, dict) or set(raw) not in (
            {'version', 'selection', 'resources', 'pending_ui'},
            {'version', 'selection', 'resources', 'pending_ui', 'ui_snapshots'}):
        raise ValueError('Invalid historical receipt')
    try:
        if not isinstance(raw['selection'], dict) or not isinstance(raw['pending_ui'], list):
            raise ValueError('Invalid historical selection')
        selection = dict(raw['selection'])
        for key in ('agents', 'features', 'shortcuts'):
            values = selection[key]
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
                raise ValueError('Invalid historical selection')
            selection[key] = frozenset(values)
        receipt = LegacyReceipt(raw['version'], LegacySelection(**selection),
                                copy.deepcopy(raw['resources']),
                                [UiStep(**s) for s in raw['pending_ui']],
                                copy.deepcopy(raw.get('ui_snapshots', {})))
        validate(receipt)
        return receipt
    except (TypeError, KeyError, AttributeError):
        raise ValueError('Invalid historical receipt') from None


def encode(receipt: LegacyReceipt) -> dict:
    """Encode recovery-only state without upgrading or losing historical inverses."""
    data = asdict(validate(receipt))
    for key in ('agents', 'features', 'shortcuts'):
        data['selection'][key] = sorted(data['selection'][key])
    return data


def resource_pairs(selection, feature, target, context, shared=None):
    """Resolve legacy feature ownership to its actual consumers, never new agents."""
    agents = selection.agents_for(feature)
    target = str(Path(target).resolve()) if target and Path(target).is_absolute() else str(target)
    if target == 'claude' or target == str(context.paths.claude_settings.resolve()):
        agents &= {'claude'}
    elif target == 'codex' or target in {str((context.paths.codex_home/name).resolve()) for name in ('config.toml','hooks.json')} or feature in {'clipboard','restore','appearance'}:
        agents &= {'codex'}
    elif shared == 'shared:shell' and feature != 'shell':
        agents &= {'codex'}
    elif shared in {'shared:hooks', 'shared:codex-hooks'}:
        agents &= {'codex','claude'} if feature == 'notifications' else {'codex'}
    return frozenset(a+':'+feature for a in agents)
