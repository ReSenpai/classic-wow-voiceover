"""Lua 5.1-окружение: грузит настоящие исходники AI_VoiceOver с заглушками WoW API."""
from pathlib import Path

from lupa import lua51

ADDON_DIR = Path(__file__).resolve().parents[2] / "AI_VoiceOver"

WOW_API_STUBS = """
format = string.format
getn = table.getn
UnitSex = function() return _UNIT_SEX end

function _register_module(name, lengths)
    local m = { METADATA = { AddonName = name }, SoundLengthLookupByFileName = lengths }
    function m:GetSoundPath(fileName) return fileName .. ".ogg" end
    VoiceOver.DataModules.registeredModulesOrdered = { m }
    VoiceOver.DataModules.GetModules = function(self) return ipairs(self.registeredModulesOrdered) end
end
"""


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

    def prepare_quest_sound(self, event_name, quest_id):
        event = self.vo.Enums.SoundEvent[event_name]
        sound = self.lua.table_from({"event": event, "questID": quest_id})
        found = self.vo.DataModules.PrepareSound(self.vo.DataModules, sound)
        return found, sound
