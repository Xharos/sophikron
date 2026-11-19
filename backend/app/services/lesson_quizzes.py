"""Save course quizzes, gate their playback and report first-passage outcomes."""

from random import SystemRandom

from sqlalchemy import select

from app.models import Promotion, Role, User, UserPromotion, UserRole
from app.models.lesson_quiz import LessonQuizPassage, LessonQuizVersion
from app.models.lessons import Lesson, LessonCollaborator, LessonElement, LessonPromotion
from app.repositories.lesson_quizzes import LessonQuizRepository
from app.schemas.lesson_quizzes import QuizAnswer, QuizProgress, QuizReplay, QuizRun, QuizStart
from app.schemas.quiz import ChoiceRule, NumberRule, TextRule
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.lessons import LessonService, effective_period
from app.services.quiz import answer_matches

RULES = {"choice": ChoiceRule, "number": NumberRule, "text": TextRule}


def shuffled(size: int, previous: list[int] | None = None) -> list[int]:
    """Return a fresh random order and avoid repeating the recorded order if possible."""
    order = SystemRandom().sample(range(size), size)
    return order[1:] + order[:1] if size > 1 and order == previous else order


def public_card(card: dict) -> dict:
    """Serialize one frozen card without its answers or tolerance."""
    return {
        **{key: value for key, value in card.items() if key != "rule"},
        "options": card["rule"].get("options", []),
    }


def correct_answer(card: dict, answer: str | list[int]) -> bool:
    """Use the bank's exact correction rules for both practice modes."""
    return answer_matches(RULES[card["kind"]].model_validate(card["rule"]), answer)


async def save_quiz_version(
    repo: LessonQuizRepository, element_id: int, subject_id: int, ids: list[int] | None
) -> bool:
    """Freeze selected cards and preserve previous definitions for removed bank entries."""
    previous = (await repo.latest([element_id])).get(element_id)
    if ids is None and previous is not None:
        return False
    if not ids or len(ids) != len(set(ids)):
        raise AuthError(422, "Sélectionnez de 1 à 50 fiches distinctes de la matière.")
    bank = await repo.bank_cards(subject_id, ids)
    old_refs = {ref["id"]: ref for ref in previous.refs} if previous else {}
    if any(identifier not in bank and identifier not in old_refs for identifier in ids):
        raise AuthError(422, "Choisissez des fiches visibles appartenant à la matière du cours.")
    refs = [
        {"id": card.id, "title": card.title, "version": card.version}
        if (card := bank.get(identifier)) is not None
        else old_refs[identifier]
        for identifier in ids
    ]
    if previous and previous.refs == refs:
        return False
    old_cards = {}
    if previous and len(bank) < len(ids):
        frozen = await repo.version(previous.id)
        old_cards = dict(zip((ref["id"] for ref in frozen.refs), frozen.cards, strict=True))
    cards = [
        {
            "title": card.title,
            "statement": card.statement,
            "prompt": card.prompt,
            "image": card.image,
            "image_alt": card.image_alt,
            "kind": card.kind,
            "rule": card.rule,
        }
        if (card := bank.get(identifier)) is not None
        else old_cards[identifier]
        for identifier in ids
    ]
    repo.db.add(LessonQuizVersion(element_id=element_id, refs=refs, cards=cards))
    await repo.db.flush()
    return True


def recorded_progress(
    passage: LessonQuizPassage | None, version: LessonQuizVersion
) -> QuizProgress:
    """Use the original passage length when an editor has changed the quiz."""
    if passage is None:
        return QuizProgress(completed=0, total=len(version.refs))
    return QuizProgress(completed=passage.position, total=len(passage.card_order), started=True)


class LessonQuizService:
    """Reuse course permissions and serialize progress with block availability changes."""

    def __init__(self, auth: AuthService) -> None:
        """Use the same request-owned resources as course editing."""
        self.auth, self.db = auth, auth.db
        self.lessons = LessonService(auth)
        self.repo = self.lessons.quiz_repo

    async def _editor(self, actor: UserContext, lesson_id: int) -> Lesson:
        """Authorize bank searches and reports only for active course editors."""
        teacher, admin = await self.lessons._principal(actor)
        lesson = await self.lessons._lesson(lesson_id)
        edit, _ = await self.lessons._edit_rights(actor, lesson, teacher, admin)
        if not edit:
            raise AuthError(403, "Accès réservé aux enseignants qui gèrent ce cours.")
        return lesson

    async def options(self, actor: UserContext, lesson_id: int, term: str) -> list[dict]:
        """Search title labels of selectable sheets in the course subject."""
        async with self.db.begin():
            lesson = await self._editor(actor, lesson_id)
            return await self.repo.bank(lesson.subject_id, term.strip())

    async def _block(self, lesson: Lesson, element_id: int) -> tuple[LessonElement, bool]:
        """Resolve a quiz scoped to the course and inherit the section audience."""
        elements = await self.lessons.repo.elements(lesson.id)
        block = next(
            (item for item in elements if item.id == element_id and item.kind == "quiz"), None
        )
        if block is None:
            raise AuthError(404, "Quiz introuvable.")
        return block, self.lessons.section_staff(block, elements)

    async def _participant(
        self, actor: UserContext, lesson_id: int, element_id: int
    ) -> LessonQuizPassage | None:
        """Apply course document visibility and lock the course during the operation."""
        teacher, admin = await self.lessons._principal(actor)
        lesson = await self.lessons._lesson(lesson_id, lock=True)
        today = self.lessons.today()
        staff = await self.lessons.staff_view(actor, lesson, teacher, admin)
        if not staff and not await self.db.scalar(
            self.lessons.repo.accessible(actor.id, today)
            .where(LessonPromotion.lesson_id == lesson_id)
            .limit(1)
        ):
            raise AuthError(403, "Votre promotion ne dispose pas d’un accès actif à ce cours.")
        block, staff_only = await self._block(lesson, element_id)
        start, end, _ = effective_period(block, (None, None, None))
        if staff_only and not staff:
            raise AuthError(404, "Quiz introuvable.")
        if not staff and ((start and today < start) or (end and today > end)):
            raise AuthError(409, "Ce quiz est en dehors de sa période de disponibilité.")
        return await self.repo.passage(element_id, actor.id)

    async def _card(self, passage: LessonQuizPassage, index: int) -> dict:
        """Resolve a frozen card of the learner's own first passage."""
        card = await self.repo.card(passage.version_id, index)
        if card is None:
            raise AuthError(404, "Fiche introuvable.")
        return card

    async def _state(self, passage: LessonQuizPassage, *, correct: bool | None = None) -> QuizRun:
        """Return the current card or the completed first passage summary."""
        total = len(passage.card_order)
        card = None
        if passage.position < total:
            card = public_card(await self._card(passage, passage.card_order[passage.position]))
        return QuizRun(
            completed=passage.position,
            total=total,
            revision=passage.revision,
            card=card,
            correct=correct,
        )

    async def start(
        self, actor: UserContext, lesson_id: int, element_id: int, data: QuizStart
    ) -> QuizRun:
        """Start once, resume in the same order, or shuffle a completed replay in memory."""
        async with self.db.begin():
            passage = await self._participant(actor, lesson_id, element_id)
            if data.replay:
                if passage is None or passage.position != len(passage.card_order):
                    raise AuthError(409, "Terminez le premier passage avant de recommencer.")
                order = shuffled(len(passage.card_order), data.previous_order or passage.card_order)

                return QuizRun(
                    completed=0,
                    total=len(order),
                    revision=0,
                    order=order,
                    card=public_card(await self._card(passage, order[0])),
                )
            if passage is None:
                version = (await self.repo.latest([element_id])).get(element_id)
                if version is None:
                    raise AuthError(409, "Ce quiz ne contient aucune fiche.")
                total = len(version.refs)
                passage = LessonQuizPassage(
                    element_id=element_id,
                    user_id=actor.id,
                    version_id=version.id,
                    card_order=shuffled(total),
                    trials=[0] * total,
                )
                self.db.add(passage)
                await self.db.flush()
            return await self._state(passage)

    async def answer(
        self, actor: UserContext, lesson_id: int, element_id: int, data: QuizAnswer
    ) -> QuizRun:
        """Count one valid response and advance only on success under the course lock."""
        async with self.db.begin():
            passage = await self._participant(actor, lesson_id, element_id)
            if passage is None or passage.position >= len(passage.card_order):
                raise AuthError(409, "Ce passage est terminé ou n’a pas encore commencé.")
            if data.revision != passage.revision:
                raise AuthError(409, "La progression a changé. Fermez puis reprenez le quiz.")

            correct = correct_answer(
                await self._card(passage, passage.card_order[passage.position]), data.answer
            )
            counts = list(passage.trials)
            counts[passage.position] += 1
            passage.trials = counts
            passage.position += int(correct)
            passage.revision += 1
            return await self._state(passage, correct=correct)

    async def replay(
        self, actor: UserContext, lesson_id: int, element_id: int, data: QuizReplay
    ) -> dict:
        """Read or correct a replay card without recording any result."""
        async with self.db.begin():
            passage = await self._participant(actor, lesson_id, element_id)
            if passage is None or passage.position != len(passage.card_order):
                raise AuthError(409, "Terminez le premier passage avant de recommencer.")

            if data.index >= len(passage.card_order):
                raise AuthError(404, "Fiche introuvable.")
            card = await self._card(passage, data.index)
            if data.answer is None:
                return {"card": public_card(card)}
            return {"correct": correct_answer(card, data.answer)}

    async def results(self, actor: UserContext, lesson_id: int, element_id: int) -> dict:
        """Summarize first passages for eligible pupils in currently granted promotions."""
        async with self.db.begin():
            lesson = await self._editor(actor, lesson_id)
            _, staff_only = await self._block(lesson, element_id)
            latest = (await self.repo.latest([element_id])).get(element_id)
            if latest is None:
                raise AuthError(404, "Quiz introuvable.")
            if staff_only:
                return {"promotions": [], "pupils": []}
            today = self.lessons.today()
            grants = select(LessonPromotion.promotion_id).where(
                LessonPromotion.lesson_id == lesson_id,
                LessonPromotion.starts_on <= today,
                LessonPromotion.ends_on >= today,
            )
            promotions = list(
                await self.db.scalars(
                    select(Promotion)
                    .where(Promotion.id.in_(grants), Promotion.is_active)
                    .order_by(Promotion.identifier, Promotion.id)
                )
            )
            rows = await self.db.execute(
                select(User, UserPromotion.promotion_id, LessonQuizPassage, LessonQuizVersion)
                .select_from(User)
                .join(UserPromotion, UserPromotion.user_id == User.id)
                .outerjoin(
                    LessonQuizPassage,
                    (LessonQuizPassage.user_id == User.id)
                    & (LessonQuizPassage.element_id == element_id),
                )
                .outerjoin(LessonQuizVersion, LessonQuizVersion.id == LessonQuizPassage.version_id)
                .where(
                    UserPromotion.promotion_id.in_([item.id for item in promotions]),
                    User.status == "active",
                    ~User.is_bootstrap,
                    User.password_hash.is_not(None),
                    ~select(LessonCollaborator.user_id)
                    .join(UserRole, UserRole.user_id == LessonCollaborator.user_id)
                    .join(Role)
                    .where(
                        LessonCollaborator.lesson_id == lesson_id,
                        LessonCollaborator.user_id == User.id,
                        Role.code == "kholleur",
                    )
                    .exists(),
                    select(UserRole.user_id)
                    .join(Role)
                    .where(
                        UserRole.user_id == User.id,
                        Role.code == "user",
                    )
                    .exists(),
                    ~select(UserRole.user_id)
                    .join(Role)
                    .where(
                        UserRole.user_id == User.id,
                        Role.code.in_(["admin", "teacher"]),
                    )
                    .exists(),
                )
            )
            pupils = {}
            for user, promotion_id, passage, version in rows:
                pupil = pupils.get(user.id)
                if pupil is None:
                    pupil = self._pupil(user, passage, version or latest)
                    pupils[user.id] = pupil
                pupil["promotion_ids"].append(promotion_id)
            return {
                "promotions": [{"id": item.id, "label": item.identifier} for item in promotions],
                "pupils": sorted(
                    pupils.values(), key=lambda item: (item["name"].casefold(), item["id"])
                ),
            }

    def _pupil(
        self, user: User, passage: LessonQuizPassage | None, version: LessonQuizVersion
    ) -> dict:
        """Build a roster entry with per-question counters and no raw answers."""
        progress = recorded_progress(passage, version)
        names = [
            self.auth.cipher.decrypt(user.id, field, getattr(user, f"{field}_encrypted"))
            for field in ("first_name", "last_name")
        ]
        cards = []
        if passage:
            cards = [
                {
                    **version.refs[index],
                    "attempts": passage.trials[step],
                    "solved": step < passage.position,
                }
                for step, index in enumerate(passage.card_order)
            ]
        return {
            **progress.model_dump(),
            "id": user.id,
            "name": " ".join(name for name in names if name) or "Élève",
            "status": (
                "not_started"
                if passage is None
                else "completed"
                if progress.completed == progress.total
                else "started"
            ),
            "trials": sum(passage.trials) if passage else 0,
            "cards": cards,
            "promotion_ids": [],
        }
