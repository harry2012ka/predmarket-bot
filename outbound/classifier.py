"""
Rule-based reply classifier.
Returns: 'interested' | 'not_interested' | 'ooo' | 'unknown'
"""

OOO_PHRASES = [
    "out of office", "out of the office", "on vacation", "on leave",
    "be back", "returning on", "away until", "away from",
    "automatic reply", "auto-reply", "maternity leave", "paternity leave",
]

NOT_INTERESTED_PHRASES = [
    "not interested", "no thanks", "no thank you", "don't contact",
    "do not contact", "remove me", "unsubscribe", "stop emailing",
    "please remove", "take me off", "opt out",
]

INTERESTED_PHRASES = [
    "interested", "tell me more", "sounds good", "sounds interesting",
    "would love", "let's chat", "let's talk", "schedule", "book a call",
    "can we", "how does", "learn more", "more info", "what's the",
    "what is the", "how much", "pricing", "demo", "free trial",
    "yes", "sure", "absolutely", "definitely", "happy to",
]


def classify_reply(body: str) -> str:
    text = body.lower()

    for phrase in OOO_PHRASES:
        if phrase in text:
            return "ooo"

    for phrase in NOT_INTERESTED_PHRASES:
        if phrase in text:
            return "not_interested"

    for phrase in INTERESTED_PHRASES:
        if phrase in text:
            return "interested"

    return "unknown"
