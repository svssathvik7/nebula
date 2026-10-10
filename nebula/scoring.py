from datetime import timedelta
from .models import Score, timestamp, utcnow

REJECTION_PENALTY = 0.02


def penalty_key(lesson_id, version):
    return f'rejection-count:{lesson_id}:{version}'


def rejection_count(store, lesson_id, version):
    from .store import StateUnavailable
    count = store.get_meta(penalty_key(lesson_id, version), 0)
    if type(count) is not int or not 0 <= count <= 50:
        raise StateUnavailable('invalid rejection penalty state')
    return count


def score(samples,*,confirmed=False,disabled=False,rejections=0):
    unique={s.episode_id:s for s in samples}
    samples=list(unique.values())
    positives=sum(s.verdict=='positive' for s in samples)
    negatives=sum(s.verdict=='negative' for s in samples)
    successful=sum(s.verdict=='positive' and s.outcome=='suitable' for s in samples)
    confidence=(positives+1)/(positives+negatives+2)
    mature=(len(unique)>=5 and len({s.session_id for s in samples})>=3 and
            len({s.project for s in samples})>=2 and successful>=3)
    penalty = min(rejections, 50) * REJECTION_PENALTY
    baseline = max(confidence, 0.80) if confirmed else confidence
    return Score(
        observational_mature=mature,
        observational_confidence=confidence,
        mature=(mature or confirmed) and not disabled,
        confidence=round(max(0.0, baseline - penalty), 12),
        positives=positives,
        negatives=negatives,
        successful_episodes=successful,
        rejection_penalty=penalty,
    )

def current_score(store,lesson,*,now=None):
    current=timestamp(now or utcnow()); cutoff=current-timedelta(days=90)
    valid=[s for s in store.samples(lesson.lesson_id,lesson.version) if cutoff<=timestamp(s.timestamp)<=current and store.sample_provenance(s.lesson_id,s.version,s.episode_id) is not None]
    return score(valid,confirmed=store.confirmed(lesson.lesson_id,lesson.version),disabled=lesson.disabled,
                 rejections=rejection_count(store,lesson.lesson_id,lesson.version))
