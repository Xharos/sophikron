# Quiz question bank

The **Quiz** menu shows counts of visible and archived questions by subject.
Teachers and administrators can browse questions and submit answers in the student
preview. Teachers can edit questions only for active subjects they are assigned
to. Administrators can manage all subjects. Preview submissions create no attempts.

The editor separates the optional statement, the question prompt and the answers.
Statements support course markup, including asterisks for bold and italic and
double equals signs for color. Prompts and options support LaTeX delimited by
`$` or `$$`. The preview tab renders the student view using the current draft.

The image drop zone accepts a static PNG or JPEG of up to 1 MiB and 4 megapixels,
with alternative text. The server validates the contents, re-encodes the image and
strips metadata before storing it. If the processed image exceeds 1 MiB, reduce
its size before saving. Optional curriculum competencies must belong to the same
subject as the question.

- **Choice** requires an exact match with the set of correct options.
- **Number** compares decimal values and integer fractions exactly. Decimal
  separators may be commas or periods. The default absolute tolerance is zero.
  For `1/2` with a tolerance of `0.01`, answers from `0.49` to `0.51` are accepted,
  including both endpoints.
- **Short text** accepts teacher-defined variants, ignoring case, accents and
  extra whitespace.

The authenticated `/api/v1/quiz` endpoint exposes counts by subject.
`/subjects/{subject_id}` returns the subject's question list, and
`/subjects/{subject_id}/questions/{question_id}` returns one question. The
`edit=true` parameter exposes the correction rule and competency IDs to editors.
`POST …/preview` returns a boolean for a submitted answer. Updates, archiving and
deletion require the version last read by the client.

Nginx must allow the same 2 MiB request limit as the `/quiz/data` route when saving
questions with images. The activity journal records creation, editing, archiving,
restoring and deletion with the acting account, title and subject. It omits
statements, answers and images.

## Quizzes in courses

Course editors can add a quiz block to a section, subsection or table cell and
select 1 to 50 visible questions from the course subject. Quiz blocks inherit
section visibility and use the same inclusive date rules as documents. The course
and block must remain accessible to start, resume or submit an answer. Staff who
can open the course can practice even outside the scheduled window. Their progress
is personal and excluded from student results.

Each student has a recorded first passage. The randomized card order and card
contents remain stable until completion. A correct answer advances to the next
card. Only valid submissions count as attempts. After completion, students can
practice again with a new order and the questions from the first passage. Practice
replays are excluded from database storage and results.

Editors can view results under each block and filter by promotions with active
course access. The first-try rate uses students who answered the card. The average
attempt count uses students who solved it. The server stores attempt counts and
omits the submitted answer text.

Deleting a quiz block or course removes its passages. A course must have zero quiz
blocks before its subject can change. See the [database migration inventory](database.md#migrations)
and [ADR 0012](decisions/0012-quiz-bank-and-course-quizzes.md) for schema and deployment details.
