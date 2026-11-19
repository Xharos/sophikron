/** Browser smoke test of an editor and a learner using the course quiz BFF. */
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { chromium } from 'playwright';

const teacher = { id: 1, label: 'Alex Exemple', role: 'teacher', can_edit: true };
let staff = true;
let started = false;
let completed = 0;
let expired = false;
let block;
let revision = 0;
const card = {
	title: 'Courant',
	statement: 'Le calibre est réglé sur courant continu.',
	prompt: 'Quelle unité ?',
	image: null,
	image_alt: '',
	kind: 'text',
	options: []
};

function element(id, kind, title, parent_id = null) {
	return {
		id,
		kind,
		title,
		parent_id,
		position: 0,
		body: '',
		schedule_mode: 'inherit',
		available: true,
		status: 'available',
		audience: 'students',
		effective_audience: 'students',
		row_index: null,
		column_index: null
	};
}

function course() {
	return {
		id: 1,
		subject_id: 1,
		title: 'Électricité',
		subject_name: 'Sciences industrielles',
		icon: 'engineering',
		color: '#41754E',
		description: '',
		responsible: teacher,
		creator: teacher,
		collaborators: [],
		promotions: [],
		warnings: [],
		staff_view: staff,
		can_edit: staff,
		today: '2026-11-19',
		version: 1,
		elements: [
			element(1, 'section', 'Chapitre 1'),
			{
				...element(3, 'table', 'Activités', 1),
				table_rows: 1,
				table_columns: ['Entraînement', 'Documents']
			},
			{
				...element(4, 'file', '', 3),
				row_index: 0,
				column_index: 1,
				file: {
					id: 7,
					extension: 'pdf',
					original_name:
						'Un document de cours avec un titre très long pour la cellule.pdf'
				}
			},
			...(block
				? [
						{
							...block,
							available: !expired,
							status: expired ? 'expired' : 'available',
							quiz_questions: staff ? [{ id: 5, title: card.title }] : null,
							quiz_progress: staff
								? { started: false, completed: 0, total: 1 }
								: { started, completed, total: 1 }
						}
					]
				: [])
		]
	};
}

const upstream = createServer(async (request, response) => {
	response.setHeader('Content-Type', 'application/json');
	const path = new URL(request.url, 'http://localhost').pathname;
	let data;
	switch (path) {
		case '/api/v1/auth/me':
			data = {
				id: staff ? 1 : 2,
				username: 'participant',
				is_bootstrap: false,
				roles: staff ? ['teacher'] : ['user'],
				permissions: staff ? ['teacher.access', 'teaching.read'] : ['user.access']
			};
			break;
		case '/api/v1/site':
			data = { settings: { name: 'Sophikron', home_text: '', text_color: '#41754E' } };
			break;
		case '/api/v1/lessons':
			data = {
				total: 2,
				offset: 0,
				limit: 24,
				can_create: false,
				items: [
					{ ...course(), can_open: true },
					{ ...course(), id: 9, title: 'Cours réservé', can_open: false }
				]
			};
			break;
		case '/api/v1/lessons/1':
			data = course();
			break;
		case '/api/v1/lessons/1/quiz-options':
			data = [{ id: 5, title: card.title }];
			break;
		case '/api/v1/lessons/1/elements': {
			const input = await body(request);
			assert.deepEqual(input.quiz_question_ids, [5]);
			assert.equal(input.kind, 'quiz');
			assert.deepEqual([input.parent_id, input.row_index, input.column_index], [3, 0, 0]);
			block = { ...element(2, 'quiz', input.title, 3), row_index: 0, column_index: 0 };
			data = course();
			response.statusCode = 201;
			break;
		}
		case '/api/v1/lessons/1/quizzes/2/start':
			if (staff) {
				data = { completed: 0, total: 1, revision: 0, card, correct: null, order: null };
				break;
			}
			started = true;
			data = {
				completed,
				total: 1,
				revision,
				card: completed ? null : card,
				correct: null,
				order: null
			};
			break;
		case '/api/v1/lessons/1/quizzes/2/answer': {
			const input = await body(request);
			assert.equal(input.revision, revision++);
			const correct = input.answer === 'ampère';
			completed = Number(correct);
			data = {
				completed,
				total: 1,
				revision,
				card: completed ? null : card,
				correct,
				order: null
			};
			break;
		}
		case '/api/v1/lessons/1/quizzes/2/results':
			data = {
				promotions: [{ id: 1, label: 'PTSI' }],
				pupils: [
					{
						id: 2,
						name: 'Morgan Exemple',
						status: 'completed',
						completed: 1,
						total: 1,
						trials: revision,
						promotion_ids: [1],
						cards: [
							{
								id: 5,
								version: 0,
								title: card.title,
								solved: true,
								attempts: revision
							}
						]
					}
				]
			};
			break;
		default:
			response.statusCode = 404;
			data = { detail: 'Route inconnue.' };
	}
	response.end(JSON.stringify(data));
});

async function body(request) {
	const chunks = [];
	for await (const chunk of request) chunks.push(chunk);
	return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

upstream.listen(0, '127.0.0.1');
await once(upstream, 'listening');
process.env.BACKEND_ORIGIN = 'http://127.0.0.1:' + upstream.address().port;
let handler;
const frontend = createServer((request, response) => handler(request, response));
let browser;
try {
	frontend.listen(0, '127.0.0.1');
	await once(frontend, 'listening');
	const origin = 'http://127.0.0.1:' + frontend.address().port;
	process.env.ORIGIN = origin;
	({ handler } = await import('../build/handler.js'));
	browser = await chromium.launch({
		headless: true,
		...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {})
	});
	const context = await browser.newContext();
	await context.addCookies([
		{ name: 'sophikron_session_dev', value: 'a'.repeat(43), url: origin }
	]);
	const page = await context.newPage();
	page.setDefaultTimeout(30000);
	await page.goto(origin + '/lessons', { waitUntil: 'networkidle' });
	const courseCard = page.getByRole('link', { name: 'Électricité', exact: true });
	assert.equal(await courseCard.locator('a, .course-open').count(), 0);
	assert.equal(await page.getByRole('link', { name: 'Cours réservé' }).count(), 0);
	await courseCard.getByText('Alex Exemple', { exact: true }).click();
	await page.waitForURL(origin + '/lessons/1');
	await page.getByRole('button', { name: 'Modifier le cours' }).click();
	await page.getByRole('cell').getByRole('button', { name: 'Quiz', exact: true }).click();
	const editor = page.getByRole('dialog');
	await editor.getByLabel('Titre', { exact: true }).fill('Entraînement');
	await editor.getByRole('checkbox', { name: 'Courant' }).check();
	await editor.getByRole('button', { name: 'Enregistrer' }).click();
	const quizTile = page.getByRole('button', { name: 'Commencer · Entraînement' });
	await quizTile.locator('svg').first().waitFor();
	assert.doesNotMatch(await quizTile.innerText(), /Commencer|Reprendre|Recommencer/);
	await quizTile.locator('.quiz-progress.is-warning').getByText('0/1').waitFor();

	staff = false;
	await page.reload({ waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Chapitre 1' }).click();
	await page.setViewportSize({ width: 540, height: 800 });
	const documentCard = page.getByRole('link', { name: /Télécharger Un document/ });
	const documentTitle = documentCard.locator('.resource-label strong');
	const quizTitle = page
		.getByRole('button', { name: 'Commencer · Entraînement' })
		.locator('.resource-label strong');
	assert.equal(await quizTitle.evaluate((node) => getComputedStyle(node).whiteSpace), 'nowrap');
	assert.ok(await documentTitle.evaluate((node) => node.scrollWidth > node.clientWidth));
	assert.equal(
		await documentTitle.evaluate((node) => getComputedStyle(node).textOverflow),
		'ellipsis'
	);
	assert.match(await documentCard.getAttribute('title'), /titre très long/);
	await page.getByRole('button', { name: 'Commencer' }).click();
	const practice = page.getByRole('dialog');
	await practice.getByLabel('Ta réponse').fill('volt');
	await practice.getByRole('button', { name: 'Valider' }).click();
	await practice.getByText('Réponse incorrecte. Réessaie.').waitFor();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Reprendre' }).click();
	await practice.getByLabel('Ta réponse').fill('ampère');
	await practice.getByRole('button', { name: 'Valider' }).click();
	await practice.getByText('Quiz terminé.').waitFor();
	await page.keyboard.press('Escape');
	await page
		.getByRole('button', { name: /Recommencer.*Entraînement/ })
		.locator('.quiz-progress.is-success')
		.getByText('1/1')
		.waitFor();

	expired = true;
	await page.reload({ waitUntil: 'networkidle' });
	await page.getByRole('button', { name: 'Chapitre 1' }).click();
	await page.getByText('Accès au quiz fermé').waitFor();
	assert.equal(await page.getByRole('button', { name: 'Recommencer' }).count(), 0);

	staff = true;
	await page.reload({ waitUntil: 'networkidle' });
	await quizTile.click();
	await page.getByRole('dialog').getByLabel('Ta réponse').waitFor();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Résultats du quiz' }).click();
	await page.getByText('Morgan Exemple').waitFor();
	await page.getByRole('cell', { name: '0 %', exact: true }).waitFor();
	console.log('Course quiz browser smoke test passed.');
} finally {
	await browser?.close();
	await new Promise((resolve) => frontend.close(resolve));
	await new Promise((done) => upstream.close(done));
}
