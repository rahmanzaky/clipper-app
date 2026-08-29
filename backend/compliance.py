"""Campaign compliance checks — catches rejection-causing mistakes before export."""
from dataclasses import dataclass, field


@dataclass
class CampaignProfile:
    topics: list = field(default_factory=list)
    min_duration: float = 8.0
    max_duration: float = 60.0
    required_hashtag: str = ""


@dataclass
class ComplianceResult:
    passed: bool
    issues: list


def check_clip(start: float, end: float, caption_text: str, profile: CampaignProfile) -> ComplianceResult:
    issues = []
    duration = end - start
    if duration < profile.min_duration:
        issues.append(f"Too short: {duration:.1f}s < min {profile.min_duration}s")
    if duration > profile.max_duration:
        issues.append(f"Too long: {duration:.1f}s > max {profile.max_duration}s")
    if profile.required_hashtag and profile.required_hashtag.lower() not in caption_text.lower():
        issues.append(f"Missing required hashtag: {profile.required_hashtag}")
    return ComplianceResult(passed=len(issues) == 0, issues=issues)
