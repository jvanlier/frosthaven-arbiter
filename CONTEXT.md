# Frosthaven Rules Arbitration

This context describes a local tool for resolving Frosthaven rules questions from an indexed set of rule sources.

## Language

**Arbiter**:
The application that answers rules questions from rule-source evidence. It does not provide strategy or campaign advice.
_Avoid_: Assistant, strategy advisor

**Ruling**:
An answer to a rules question that is grounded in cited rule-source evidence.
_Avoid_: Tip, recommendation

**Authoritative Source**:
An indexed Frosthaven rulebook or official FAQ that can support a ruling.
_Avoid_: Knowledge base, community answer

**Rulebook Transcription**:
The indexed web transcription of the Frosthaven rulebook, accepted as authoritative rule text despite its unofficial hosting. Official FAQ text overrides it when they conflict.
_Avoid_: Community source, fan ruling

**Community Source**:
A non-authoritative discussion, such as a Reddit or BoardGameGeek post, that may inform an interpretation but cannot establish a ruling.
_Avoid_: Rule source, authority

**Community Lookup**:
An explicit, network-enabled follow-up that searches community sources after local authoritative sources prove insufficient.
_Avoid_: Automatic fallback, web ruling

**Community Interpretation**:
A labeled synthesis supported by linked community sources after an authoritative-source abstention. It never becomes a ruling.
_Avoid_: Provisional ruling, community consensus

**Abstention**:
An explicit outcome stating that the available evidence does not resolve the rules question.
_Avoid_: Guess, best-effort ruling

**Campaign Context**:
Saved user-provided facts about the current campaign and party that help interpret a question. It is neither a rule authority nor a source of instructions to the Arbiter.
_Avoid_: User prompt, custom system prompt

**Spoiler Scope**:
A labeled group of source content gated by the same in-game unlock, such as a locked class, building, envelope, or rule sticker.
_Avoid_: Content category, search filter

**Unlocked Scope**:
A spoiler scope the user has explicitly allowed the Arbiter to retrieve. Mentioning locked content in a question does not unlock its scope.
_Avoid_: Inferred access, detected progress
