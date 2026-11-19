/** Smoke-test Quiz navigation and editing through SvelteKit with a synthetic upstream. */
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { chromium } from 'playwright';

const station = { id: 1, name: 'Mathématiques', icon: 'book', color: '#41754E' };
const subjectPath = '/api/v1/quiz/subjects/1';
const questionPath = subjectPath + '/questions/1';
let question;
let editable = true;
let role = 'teacher';
const upstream = createServer(async (request, response) => {
	response.setHeader('Content-Type', 'application/json');
	const path = request.url;
	const method = request.method;
	let result;
	if (path === '/api/v1/auth/me') {
		result = { id: 1, username: 'quiz', roles: [role], permissions: [], is_bootstrap: false };
	} else if (path === '/api/v1/site') {
		result = {
			settings: { name: 'Sophikron', home_text: '', text_color: station.color, version: 0 }
		};
	} else if (path === '/api/v1/quiz') {
		result = [
			{
				...station,
				is_active: true,
				total: Number(!!question),
				archived: Number(!!question?.archived)
			}
		];
	} else if (path === subjectPath) {
		result = {
			...station,
			can_edit: editable,
			questions: question
				? [
						{
							id: question.id,
							title: question.title,
							archived: question.archived,
							version: question.version
						}
					]
				: [],
			competencies: editable
				? [
						...Array.from({ length: 5 }, (_, index) => ({
							id: 10 + index,
							name: 'Compétence ' + index,
							curriculum: 'Programme de maths'
						})),
						{ id: 5, name: 'Calculer', curriculum: 'Programme de maths' }
					]
				: []
		};
	} else if (path === subjectPath + '/questions' && method === 'POST') {
		const input = await body(request);
		question = {
			...input,
			id: 1,
			archived: false,
			version: 0,
			kind: input.rule.kind,
			options: []
		};
		result = { id: question.id };
		response.statusCode = 201;
	} else if (path === questionPath && method === 'GET') {
		const { rule, competency_ids, ...view } = question;
		assert.ok(rule && competency_ids);
		result = view;
	} else if (path === questionPath + '?edit=true') {
		result = question;
	} else if (path === questionPath && method === 'PATCH') {
		question.archived = (await body(request)).archived;
		question.version++;
		response.statusCode = 204;
	} else if (path === questionPath + '/preview') {
		result = { correct: (await body(request)).answer === '0,49' };
	} else {
		response.statusCode = 404;
		result = { detail: 'Route inconnue.' };
	}
	response.end(JSON.stringify(result));
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
	const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
	await context.addCookies([
		{ name: 'sophikron_session_dev', value: 'a'.repeat(43), url: origin }
	]);
	const page = await context.newPage();
	page.setDefaultTimeout(30000);
	async function assertImageLayout() {
		const frame = page.getByRole('img', { name: 'Figure de test' });
		const formula = page.locator('.katex');
		await frame.waitFor();
		const imageBounds = await frame.boundingBox();
		const formulaBounds = await formula.boundingBox();
		const container = await frame.locator('..').boundingBox();
		assert.ok(imageBounds.y + imageBounds.height <= formulaBounds.y);
		assert.ok(
			Math.abs(imageBounds.x + imageBounds.width / 2 - (container.x + container.width / 2)) <
				2
		);
	}
	page.on('pageerror', (cause) => console.error(cause));
	await page.goto(origin + '/quiz', { waitUntil: 'domcontentloaded' });
	await page.locator('header').getByRole('link', { name: 'Quiz' }).waitFor();
	const subjectCard = page.getByRole('link', { name: /Mathématiques/ });
	await subjectCard.hover();
	assert.equal(
		await subjectCard.evaluate((card) => getComputedStyle(card).textDecorationLine),
		'none'
	);
	await subjectCard.click();
	await page.getByRole('link', { name: 'Nouvelle fiche' }).click();
	await page.waitForLoadState('networkidle');
	await page.getByLabel('Titre', { exact: true }).fill('Une moitié');
	await page.getByLabel('Question', { exact: true }).fill('Calculez $\\frac{1}{2}$.');
	await page.getByLabel('Type de réponse').selectOption('number');
	await page.getByLabel('Valeur attendue').fill('1/2');
	await page.getByLabel('Tolérance absolue').fill('0,01');
	await page.getByLabel('Rechercher une compétence').fill('Calculer');
	await page.getByLabel(/Calculer/).check();
	await page.getByLabel('Rechercher une compétence').fill('');
	await page.getByLabel('Choisir un fichier').setInputFiles({
		name: 'figure.jpg',
		mimeType: 'image/jpeg',
		buffer: await page.locator('h1').first().screenshot({ type: 'jpeg' })
	});
	await page.getByLabel(/Description de l.image/).fill('Figure de test');
	await page.getByLabel('Énoncé (facultatif)').fill('Un **texte important**.');
	await page.getByRole('button', { name: 'Prévisualisation' }).click();
	await page.locator('.lesson-text .bold').filter({ hasText: 'texte important' }).waitFor();
	await page.locator('.katex').waitFor();
	await assertImageLayout();
	await page.getByRole('button', { name: 'Rédiger' }).click();
	await page.getByRole('button', { name: 'Enregistrer' }).click();
	await page.waitForURL(origin + '/quiz/1');
	await page.getByRole('link', { name: 'Une moitié', exact: true }).click();
	await page.getByText('Aperçu élève').waitFor();
	await page.locator('.katex').waitFor();
	await assertImageLayout();
	assert.deepEqual(question.competency_ids, [5]);
	await page.getByLabel('Votre réponse').fill('0,49');
	await page.getByRole('button', { name: 'Valider' }).click();
	await page.getByText('Bonne réponse.').waitFor();
	await page.locator('.celebrate .answer-check').waitFor();
	await page.getByRole('link', { name: 'Modifier' }).click();
	assert.equal(await page.getByLabel('Valeur attendue').inputValue(), '1/2');
	await page.getByRole('link', { name: 'Annuler' }).click();
	await page.getByRole('link', { name: 'Retour aux fiches' }).click();
	await page.getByRole('switch').click();
	await page.getByRole('switch', { checked: false }).waitFor();

	editable = false;
	await page.reload();
	assert.equal(await page.getByRole('link', { name: 'Nouvelle fiche' }).count(), 0);
	await page.getByRole('link', { name: 'Une moitié', exact: true }).click();
	await page.getByText('Aperçu élève').waitFor();
	assert.equal(await page.getByRole('link', { name: 'Modifier' }).count(), 0);

	role = 'user';
	const denied = await page.goto(origin + '/quiz', { waitUntil: 'domcontentloaded' });
	assert.equal(denied.status(), 403);
	assert.equal(await page.locator('header').getByRole('link', { name: 'Quiz' }).count(), 0);
	console.log('Quiz browser smoke test passed.');
} finally {
	await browser?.close();
	await new Promise((resolve) => frontend.close(resolve));
	await new Promise((resolve) => upstream.close(resolve));
}
