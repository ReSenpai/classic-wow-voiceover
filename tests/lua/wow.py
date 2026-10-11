"""Lua 5.1-окружение: грузит настоящие исходники AI_VoiceOver с заглушками WoW API."""
from pathlib import Path

from lupa import lua51

ADDON_DIR = Path(__file__).resolve().parents[2] / "AI_VoiceOver"

WOW_API_STUBS = """
format = string.format
getn = table.getn
UnitSex = function() return _UNIT_SEX end
_TOC = {}
GetAddOnMetadata = function(name, key) return _TOC[name] and _TOC[name][key] end

function _register_module(name, lengths)
    local m = { METADATA = { AddonName = name }, SoundLengthLookupByFileName = lengths }
    function m:GetSoundPath(fileName) return fileName .. ".ogg" end
    VoiceOver.DataModules.registeredModulesOrdered = { m }
    VoiceOver.DataModules.GetModules = function(self) return ipairs(self.registeredModulesOrdered) end
end

function _present(name)
    local toc = _TOC[name]
    VoiceOver.DataModules.presentModules[name] = {
        AddonName = name,
        ModulePriority = tonumber(toc["X-VoiceOver-DataModule-Priority"]) or 0,
    }
end

function _register_legacy(name, priority, lengths)
    _TOC[name] = { ["X-VoiceOver-DataModule-Version"] = "1", ["X-VoiceOver-DataModule-Priority"] = tostring(priority) }
    _present(name)
    local m = { SoundLengthLookupByFileName = lengths }
    function m:GetSoundPath(fileName) return "legacy\\\\" .. fileName .. ".ogg" end
    VoiceOver.DataModules:Register(name, m)
end
"""


def parse_toc(path: Path):
    metadata, files = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            key, _, value = line[3:].partition(":")
            metadata[key.strip()] = value.strip()
        elif line.strip() and not line.startswith("#"):
            files.append(line.strip())
    return metadata, files


class WowLua:
    def __init__(self, files=("Environment.lua", "Enums.lua", "DataModules.lua")):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(WOW_API_STUBS)
        for name in files:
            self.load(name)

    def load(self, name):
        self.lua.execute((ADDON_DIR / name).read_text(encoding="utf-8"))

    @property
    def vo(self):
        return self.lua.globals().VoiceOver

    def set_player_sex(self, sex):
        self.lua.globals()._UNIT_SEX = sex

    def register_module(self, name, lengths):
        self.lua.globals()._register_module(name, self.lua.table_from(lengths))

    def register_legacy_module(self, name, priority, lengths):
        """Модуль-«старый пак», зарегистрированный настоящим DataModules:Register."""
        self.lua.globals()._register_legacy(name, priority, self.lua.table_from(lengths))

    def install_addon(self, addon_dir: Path):
        """Как клиент: читает .toc, отдаёт метаданные и исполняет перечисленные файлы по порядку."""
        name = addon_dir.name
        metadata, files = parse_toc(addon_dir / f"{name}.toc")
        self.lua.globals()._TOC[name] = self.lua.table_from(metadata)
        self.lua.globals()._present(name)
        for relative in files:
            self.lua.execute((addon_dir / relative.replace("\\", "/")).read_text(encoding="utf-8"))
        return metadata

    def prepare_quest_sound(self, event_name, quest_id):
        event = self.vo.Enums.SoundEvent[event_name]
        sound = self.lua.table_from({"event": event, "questID": quest_id})
        found = self.vo.DataModules.PrepareSound(self.vo.DataModules, sound)
        return found, sound
