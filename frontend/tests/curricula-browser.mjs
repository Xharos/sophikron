/** Browser interactions against synthetic HTTP fixtures; API rights have PostgreSQL tests. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { createServer as createViteServer } from 'vite';
import { chromium } from 'playwright';

const colors = ['#4361EE', '#8B5CF6', '#0891B2', '#D97706', '#DB2777', '#059669', '#E05252'];
const names = [
	'Analyser',
	'Modéliser',
	'Résoudre',
	'Expérimenter',
	'Communiquer',
	'Concevoir',
	'Réaliser'
];
let sequence = 1;
function node(name, code, color = null) {
	return {
		id: sequence++,
		name,
		code,
		color,
		semester: null,
		knowledge: null,
		comment: null,
		position: sequence
	};
}
const roots = names.map((name, i) => node(name, String.fromCharCode(65 + i), colors[i]));
const graph = { curriculum_id: 1, subject_id: 1, version: 0, nodes: [...roots], edges: [] };
for (const root of roots) {
	for (let i = 1; i <= 2; i++) {
		const child = node(`${root.name} : compétence attendue ${i}`, `${root.code}${i}`);
		const leaf = node(`Mettre en œuvre une démarche pour ${root.name.toLowerCase()}`, null);
		leaf.semester = i;
		leaf.knowledge = 'Connaissances associées au programme officiel.';
		graph.nodes.push(child, leaf);
		graph.edges.push(
			{ parent_id: root.id, child_id: child.id },
			{ parent_id: child.id, child_id: leaf.id }
		);
	}
}
graph.edges.push({ parent_id: roots[1].id, child_id: graph.nodes[8].id });
const catalog = {
	can_manage: true,
	curricula: [
		{
			id: 1,
			title: 'Programme PTSI / PT',
			is_active: true,
			version: 0,
			source_url: 'https://education.gouv.fr/programme.pdf',
			subject_ids: [1, 2, 3, 4]
		},
		{
			id: 2,
			title: 'Autre référentiel',
			is_active: true,
			version: 0,
			source_url: null,
			subject_ids: [2]
		}
	],
	subjects: [
		{
			id: 1,
			name: 'Sciences industrielles de l’ingénieur',
			icon: 'engineering',
			color: colors[0],
			is_active: true,
			can_edit: true
		},
		{
			id: 2,
			name: 'Mathématiques',
			icon: 'calculator',
			color: colors[1],
			is_active: true,
			can_edit: true
		},
		{
			id: 3,
			name: 'Physique',
			icon: 'engineering',
			color: colors[2],
			is_active: true,
			can_edit: true
		},
		{
			id: 4,
			name: 'Chimie',
			icon: 'engineering',
			color: colors[3],
			is_active: true,
			can_edit: true
		}
	]
};
const user = {
	id: 1,
	username: 'preview',
	first_name: 'Camille',
	last_name: 'Exemple',
	roles: ['admin'],
	permissions: ['users.manage', 'users.read', 'curricula.read', 'curricula.manage'],
	is_bootstrap: false
};
const errors = [];
const undoStack = [];
const backend = createServer(async (request, response) => {
	response.setHeader('Content-Type', 'application/json');
	const path = request.url;
	let result;
	if (path === '/api/v1/auth/me') result = user;
	else if (path === '/api/v1/site')
		result = {
			settings: { name: 'Sophikron', home_text: '', text_color: colors[0], version: 0 }
		};
	else if (path === '/api/v1/curricula/catalog') result = catalog;
	else if (path === '/api/v1/curricula' && request.method === 'POST') {
		let body = '';
		for await (const chunk of request) body += chunk;
		const input = JSON.parse(body);
		assert.ok(!('track_id' in input));
		result = { id: 3, version: 0, ...input };
		catalog.curricula.push(result);
	} else if (path === '/api/v1/curricula/1/subjects/1') result = graph;
	else if (/^\/api\/v1\/curricula\/[123]\/subjects\/2$/.test(path))
		result = {
			curriculum_id: Number(path.split('/')[4]),
			subject_id: 2,
			version: 0,
			nodes: [node('Raisonner et démontrer', 'M')],
			edges: []
		};
	else if (/^\/api\/v1\/curricula\/1\/subjects\/[34]$/.test(path))
		result = {
			curriculum_id: 1,
			subject_id: Number(path.split('/').at(-1)),
			version: graph.version,
			nodes: [],
			edges: []
		};
	else if (request.method === 'POST' && /\/nodes$/.test(path)) {
		undoStack.push(structuredClone(graph));
		let body = '';
		for await (const chunk of request) body += chunk;
		const data = JSON.parse(body);
		assert.ok(!('code' in data));
		const created = { ...node(data.name, 'A.3'), ...data };
		graph.nodes.push(created);
		graph.edges.push(...data.parent_ids.map((id) => ({ parent_id: id, child_id: created.id })));
		graph.version++;
		graph.can_undo = true;
		result = graph;
	} else if (request.method === 'PUT' && /\/nodes\/\d+$/.test(path)) {
		undoStack.push(structuredClone(graph));
		let body = '';
		for await (const chunk of request) body += chunk;
		const data = JSON.parse(body);
		const target = graph.nodes.find((n) => n.id === Number(path.split('/').at(-1)));
		Object.assign(target, data);
		graph.edges = [
			...graph.edges.filter((e) => e.child_id !== target.id),
			...data.parent_ids.map((id) => ({ parent_id: id, child_id: target.id }))
		];
		graph.version++;
		graph.can_undo = true;
		result = graph;
	} else if (path === '/api/v1/curricula/1/undo') {
		const previous = undoStack.pop(),
			version = graph.version + 1;
		Object.assign(graph, previous);
		graph.version = version;
		graph.can_undo = undoStack.length > 0;
		result = graph;
	} else if (path === '/api/v1/curricula/1/subjects/1/export') {
		result = {
			format: 'sophikron.competencies',
			version: 1,
			subject_name: catalog.subjects[0].name,
			nodes: graph.nodes.map((item) => ({
				id: item.id,
				name: item.name,
				semester: item.semester,
				knowledge: item.knowledge,
				comment: item.comment ?? null,
				color: item.color,
				position: item.position,
				parent_ids: graph.edges
					.filter((edge) => edge.child_id === item.id)
					.map((edge) => edge.parent_id)
			}))
		};
	} else if (path === '/api/v1/curricula/1/subjects/1/import') {
		let body = '';
		for await (const chunk of request) body += chunk;
		const input = JSON.parse(body),
			document = JSON.parse(input.document);
		assert.equal(input.expected_version, graph.version);
		undoStack.push(structuredClone(graph));
		const mapped = new Map(document.nodes.map((item) => [item.id, sequence++]));
		for (const item of document.nodes) {
			graph.nodes.push({ ...item, id: mapped.get(item.id), code: 'Imported' });
			graph.edges.push(
				...item.parent_ids.map((parent) => ({
					parent_id: mapped.get(parent),
					child_id: mapped.get(item.id)
				}))
			);
		}
		graph.version++;
		graph.can_undo = true;
		result = graph;
	} else {
		response.statusCode = 404;
		result = { detail: `Unknown fixture: ${path}` };
	}
	response.end(JSON.stringify(result));
});
backend.listen(0, '127.0.0.1');
await once(backend, 'listening');
process.env.BACKEND_ORIGIN = `http://127.0.0.1:${backend.address().port}`;
const vite = await createViteServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
await vite.listen();
const origin = `http://127.0.0.1:${vite.httpServer.address().port}`;
process.env.ORIGIN = origin;
let browser;
try {
	browser = await chromium.launch({
		headless: true,
		...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {})
	});
	const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
	await context.addCookies([
		{ name: 'sophikron_session_dev', value: 'a'.repeat(43), url: origin }
	]);
	const page = await context.newPage();
	async function clickButton(locator) {
		await locator.waitFor();
		if (!(await locator.evaluate((element) => !!element.closest('.graph-label')))) {
			await locator.click();
			return;
		}
		await page.waitForTimeout(500);
		let box = await locator.boundingBox();
		for (let attempt = 0; attempt < 25; attempt++) {
			await page.waitForTimeout(80);
			const next = await locator.boundingBox();
			assert.ok(box && next);
			const settled = Math.abs(next.x - box.x) + Math.abs(next.y - box.y) < 0.6;
			box = next;
			if (settled) break;
		}
		assert.ok(box);
		const unobstructed = await locator.evaluate((element) => {
			const rect = element.getBoundingClientRect();
			return element.contains(
				document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
			);
		});
		if (!unobstructed) {
			await locator.focus();
			await locator.press('Enter');
			return;
		}
		await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
	}

	page.on('pageerror', (error) => {
		errors.push(error.message);
		console.error(error.message);
	});
	await page.goto(`${origin}/curricula`);
	await page.locator('.master-title').first().waitFor();
	await page.waitForTimeout(800);
	assert.equal(await page.locator('.master-title').count(), 4);
	await page.waitForFunction(
		(count) =>
			document.querySelector(
				'[aria-label="Déplier Sciences industrielles de l’ingénieur"] span'
			)?.textContent === String(count),
		roots.length
	);
	await clickButton(
		page.getByRole('button', { name: 'Sciences industrielles de l’ingénieur', exact: true })
	);
	await page.waitForTimeout(900);
	await page.locator('.node-title').first().waitFor();
	assert.equal(await page.locator('.node-title').count(), 7);
	assert.deepEqual(
		await page.locator('.graph-label').evaluateAll((labels) =>
			labels
				.filter((label) => {
					const outer = label.getBoundingClientRect();
					return [...label.querySelectorAll('.node-actions button')].some(
						(button) => button.getBoundingClientRect().bottom > outer.bottom + 0.5
					);
				})
				.map((label) => label.dataset.nodeId)
		),
		[],
		'Graph action buttons must stay within their frame.'
	);
	await page.getByRole('button', { name: 'Plein écran', exact: true }).click();
	await page.waitForFunction(() => !!document.fullscreenElement);
	await page.getByRole('button', { name: 'Quitter le plein écran', exact: true }).click();
	await page.waitForFunction(() => !document.fullscreenElement);
	await page.getByRole('button', { name: 'Plein écran', exact: true }).click();
	await page.waitForFunction(() => !!document.fullscreenElement);
	await page.evaluate(() => document.exitFullscreen());
	await page.getByRole('button', { name: 'Plein écran', exact: true }).waitFor();
	await clickButton(page.getByRole('button', { name: 'Vue textuelle', exact: true }));
	const summary = page.getByRole('list', {
		name: 'Sommaire de Sciences industrielles de l’ingénieur'
	});
	assert.equal(await summary.locator('.text-node').count(), graph.nodes.length);
	const summaryRows = await summary.locator('li').evaluateAll((items) =>
		items.slice(0, 2).map((item) => ({
			depth: Number(item.dataset.depth),
			x: item.querySelector('button').getBoundingClientRect().x,
			height: item.querySelector('button').getBoundingClientRect().height,
			color: getComputedStyle(item.querySelector('button')).borderLeftColor
		}))
	);
	assert.equal(summaryRows[0].depth, 0);
	assert.equal(summaryRows[1].depth, 1);
	assert.ok(summaryRows[1].x > summaryRows[0].x);
	assert.equal(summaryRows[1].color, summaryRows[0].color);
	assert.ok(summaryRows.every((row) => row.height < 35));
	await clickButton(page.getByRole('button', { name: 'Vue graphique', exact: true }));
	await clickButton(page.getByRole('button', { name: 'Déplier Analyser', exact: true }));
	assert.equal(await page.locator('.node-title').count(), 9);
	await clickButton(
		page.getByRole('button', { name: 'Déplier Analyser : compétence attendue 1', exact: true })
	);
	assert.equal(await page.locator('.node-title').count(), 10);
	const hierarchyStyles = await page.locator('.graph-label[data-depth]').evaluateAll((elements) =>
		elements.map((element) => ({
			depth: Number(element.dataset.depth),
			scale: new DOMMatrix(getComputedStyle(element).transform).a,
			filter: getComputedStyle(element).filter
		}))
	);
	const parentStyle = hierarchyStyles.find((item) => item.depth === 1);
	const childStyle = hierarchyStyles.find((item) => item.depth === 2);
	assert.ok(
		childStyle.filter !== parentStyle.filter,
		'Descendants should use a quieter palette.'
	);
	await clickButton(
		page.getByRole('button', { name: 'Replier Analyser : compétence attendue 1', exact: true })
	);
	await page.waitForTimeout(500);
	assert.equal(await page.locator('.node-title').count(), 9);
	const viewport = await page.locator('.graph-space').boundingBox();
	await page.getByLabel('Rechercher une compétence').fill('Analyser : compétence attendue 1');
	assert.ok(await page.locator('.search-results .result-dot').count());
	assert.ok(
		(await page.locator('.search-results small').first().textContent()).includes(
			'Sciences industrielles'
		)
	);
	await page.locator('.search-results button').first().click();
	await page.waitForTimeout(500);
	assert.ok((await page.locator('.graph-label.highlighted').count()) >= 3);
	await page.waitForTimeout(10100);
	assert.equal(await page.locator('.graph-label.highlighted').count(), 0);
	await page.mouse.move(viewport.x + 70, viewport.y + 200);
	const zoomBefore = Number(await page.locator('.graph-space').getAttribute('data-zoom'));
	await page.mouse.wheel(0, -350);
	await page.waitForFunction(
		(z) => Number(document.querySelector('.graph-space').dataset.zoom) > z + 0.1,
		zoomBefore
	);
	const panBefore = Number(await page.locator('.graph-space').getAttribute('data-pan-x'));
	await page.mouse.down();
	await page.mouse.move(viewport.x + 190, viewport.y + 250, { steps: 8 });
	await page.mouse.up();
	await page.waitForFunction(
		(x) => Number(document.querySelector('.graph-space').dataset.panX) > x + 60,
		panBefore
	);
	await clickButton(page.getByRole('button', { name: 'Replier Analyser', exact: true }));
	await clickButton(page.getByRole('button', { name: 'Déplier Analyser', exact: true }));
	await page.waitForTimeout(900);
	const automaticPan = Number(await page.locator('.graph-space').getAttribute('data-pan-x'));
	const automaticZoom = Number(await page.locator('.graph-space').getAttribute('data-zoom'));
	await clickButton(page.getByRole('button', { name: 'Recentrer', exact: true }));
	await page.waitForTimeout(500);
	assert.ok(
		Math.abs(
			Number(await page.locator('.graph-space').getAttribute('data-pan-x')) - automaticPan
		) < 2
	);
	assert.ok(
		Math.abs(
			Number(await page.locator('.graph-space').getAttribute('data-zoom')) - automaticZoom
		) < 0.01
	);
	await page.keyboard.press('Space');
	await page.waitForTimeout(700);
	const centeredPan = Number(await page.locator('.graph-space').getAttribute('data-pan-x'));
	await clickButton(page.getByRole('button', { name: 'Recentrer', exact: true }));
	await page.waitForTimeout(700);
	assert.ok(
		Math.abs(
			Number(await page.locator('.graph-space').getAttribute('data-pan-x')) - centeredPan
		) < 2
	);
	const label = page.locator('[data-node-id="1"]');
	const rest = await label.boundingBox();
	const title = await label.locator('.node-title').boundingBox();
	await page.mouse.move(title.x + title.width / 2, title.y + 5);
	await page.mouse.down();
	await page.mouse.move(title.x + title.width / 2 + 110, title.y + 65, { steps: 10 });
	const displaced = await label.boundingBox();
	assert.ok(displaced.x > rest.x + 60, 'Node should follow the pointer while dragged.');
	await page.mouse.up();
	await page.waitForTimeout(2500);
	const returned = await label.boundingBox();
	assert.ok(
		Math.abs(returned.x - rest.x) < 25,
		'Released node should return towards its resting position.'
	);
	await clickButton(page.getByRole('button', { name: 'Détails de Analyser', exact: true }));
	assert.equal(
		await page
			.locator('details')
			.filter({ has: page.locator('summary', { hasText: /^Semestre$/ }) })
			.getAttribute('open'),
		null
	);
	await page.getByText('Présentation', { exact: true }).click();
	const hex = page.getByLabel('Code couleur hexadécimal');
	await hex.fill('#aabbcc');
	assert.equal(await page.locator('#competency-color').inputValue(), '#aabbcc');
	await page.locator('#competency-color').fill('#112233');
	assert.equal(await hex.inputValue(), '#112233');
	const actionRows = await page
		.locator('.competency-actions .button')
		.evaluateAll((buttons) =>
			buttons.map((button) => Math.round(button.getBoundingClientRect().y))
		);
	assert.equal(new Set(actionRows).size, 1);
	const actions = await page.locator('.competency-actions').evaluate((element) => ({
		left: element.getBoundingClientRect().left,
		right: element.getBoundingClientRect().right,
		buttons: [...element.querySelectorAll('button')].map((button) => ({
			left: button.getBoundingClientRect().left,
			right: button.getBoundingClientRect().right
		}))
	}));
	assert.ok(Math.abs(actions.buttons[0].left - actions.left) < 2);
	assert.ok(Math.abs(actions.buttons.at(-1).right - actions.right) < 2);
	assert.ok(actions.buttons[2].left - actions.buttons[1].right > 8);
	await page.getByLabel('Nom', { exact: true }).fill('Analyser un système');
	await clickButton(page.getByRole('button', { name: 'Enregistrer', exact: true }));
	await page.getByRole('dialog').waitFor({ state: 'detached' });
	assert.equal(graph.nodes[0].name, 'Analyser un système');
	await clickButton(
		page.getByRole('button', { name: 'Ajouter sous Analyser un système', exact: true })
	);
	assert.equal(await page.getByLabel('Connaissances associées').isVisible(), false);
	assert.equal(await page.getByLabel('Code facultatif').count(), 0);
	await page.getByLabel('Nom', { exact: true }).fill('Créée avec Entrée');
	await page.getByLabel('Nom', { exact: true }).press('Enter');
	await page.getByRole('dialog').waitFor({ state: 'detached' });
	assert.ok(graph.nodes.some((node) => node.name === 'Créée avec Entrée'));
	await page.getByRole('button', { name: 'Déplier Créée avec Entrée', exact: true }).waitFor();
	assert.equal(
		await page.getByRole('button', { name: 'A.3 Créée avec Entrée', exact: true }).count(),
		1
	);
	await page.keyboard.press('Control+z');
	await page.waitForTimeout(600);
	assert.ok(!graph.nodes.some((node) => node.name === 'Créée avec Entrée'));
	await page.getByRole('button', { name: 'Annuler l’action (Ctrl+Z)', exact: true }).click();
	await page.waitForTimeout(500);
	assert.equal(graph.nodes[0].name, 'Analyser');
	await page
		.getByRole('button', { name: 'Isoler Sciences industrielles de l’ingénieur', exact: true })
		.click();
	await page.waitForTimeout(500);
	assert.equal(await page.locator('.master-title').count(), 1);
	await page.getByRole('button', { name: 'Tout afficher', exact: true }).click();
	await page.waitForTimeout(500);
	assert.equal(await page.locator('.master-title').count(), 4);
	async function assertVisibleLabels() {
		assert.deepEqual(
			await page
				.locator('.graph-label')
				.evaluateAll((elements) =>
					elements
						.filter((element) => Number(getComputedStyle(element).opacity) < 0.99)
						.map((element) => element.dataset.nodeId)
				),
			[],
			'Every restored label must remain opaque after its transition.'
		);
	}
	await assertVisibleLabels();
	for (let i = 0; i < 3; i++) {
		await page
			.getByRole('button', {
				name: 'Isoler Sciences industrielles de l’ingénieur',
				exact: true
			})
			.click();
		await page.waitForTimeout(60);
		await page.getByRole('button', { name: 'Tout afficher', exact: true }).click();
	}
	await page.waitForTimeout(900);
	await assertVisibleLabels();
	await page.getByRole('button', { name: 'Masquer Physique', exact: true }).click();
	await page.waitForTimeout(40);
	await page.getByRole('button', { name: 'Afficher Physique', exact: true }).click();
	await page.waitForTimeout(900);
	await assertVisibleLabels();
	assert.equal(await page.locator('.master-title').count(), 4);
	const sizes = await page
		.locator('.graph-label')
		.evaluateAll((elements) =>
			elements.map((element) => element.getBoundingClientRect().width)
		);
	assert.ok(
		Math.min(...sizes) > 40,
		'Four subjects and an expanded branch should remain readable.'
	);
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.getByRole('button', { name: 'Isoler Chimie', exact: true }).click();
	await page.waitForTimeout(50);
	await page.getByRole('button', { name: 'Tout afficher', exact: true }).click();
	await page.waitForTimeout(100);
	await assertVisibleLabels();
	assert.equal(await page.locator('.master-title').count(), 4);
	await page.emulateMedia({ reducedMotion: 'no-preference' });
	if (process.env.CURRICULA_SCREENSHOT) {
		await clickButton(page.getByRole('button', { name: 'B Modéliser', exact: true }));
		await page.waitForTimeout(2500);
		await page.screenshot({ path: process.env.CURRICULA_SCREENSHOT, fullPage: true });
	}
	await clickButton(page.getByRole('button', { name: 'Mathématiques', exact: true }));
	await page.getByRole('button', { name: 'M Raisonner et démontrer', exact: true }).waitFor();
	assert.equal(await page.locator('.master-title').count(), 4);
	await page.getByRole('button', { name: 'Exporter les compétences', exact: true }).click();
	const downloadPromise = page.waitForEvent('download');
	await page.getByRole('button', { name: 'Télécharger', exact: true }).click();
	const download = await downloadPromise;
	assert.equal(download.suggestedFilename(), `${catalog.subjects[0].name}.json`);
	const stream = await download.createReadStream();
	const chunks = [];
	for await (const chunk of stream) chunks.push(chunk);
	const exported = JSON.parse(Buffer.concat(chunks).toString('utf8'));
	assert.equal(exported.nodes.length, graph.nodes.length);
	assert.equal(exported.format, 'sophikron.competencies');
	await page.getByRole('button', { name: 'Importer des compétences', exact: true }).click();
	await page
		.getByRole('dialog')
		.locator('input[type=file]')
		.setInputFiles({
			name: 'bad.json',
			mimeType: 'application/json',
			buffer: Buffer.from('not json')
		});
	assert.ok(await page.getByRole('alert').isVisible());
	assert.ok(await page.getByRole('button', { name: 'Importer', exact: true }).isDisabled());
	exported.nodes[0].comment = 'n'.repeat(10000);
	exported.nodes[1].comment = 'n'.repeat(10000);
	await page.getByRole('group', { name: 'Dépôt de document' }).evaluate((element, content) => {
		const transfer = new DataTransfer();
		transfer.items.add(new File([content], 'competences.json', { type: 'application/json' }));
		element.dispatchEvent(
			new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer })
		);
	}, JSON.stringify(exported));
	await page.getByText('competences.json', { exact: true }).waitFor();
	const initialCount = graph.nodes.length;
	await page.getByRole('button', { name: 'Importer', exact: true }).click();
	await page.getByRole('dialog').waitFor({ state: 'detached' });
	assert.equal(graph.nodes.length, initialCount * 2);
	await page.getByRole('button', { name: 'Annuler l’action (Ctrl+Z)', exact: true }).click();
	await page.waitForTimeout(600);
	assert.equal(graph.nodes.length, initialCount);
	await page.getByLabel('Référentiel', { exact: true }).selectOption('2');
	await clickButton(page.getByRole('button', { name: 'Mathématiques', exact: true }));
	await page.getByRole('button', { name: 'M Raisonner et démontrer', exact: true }).waitFor();
	assert.equal(await page.locator('.node-title').count(), 1);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.locator('.text-node').waitFor({ state: 'visible' });
	assert.equal(await page.locator('.text-node').count(), 1);
	assert.equal(await page.getByRole('button', { name: 'Vue graphique', exact: true }).count(), 0);
	assert.ok(!(await page.locator('.graph-space').isVisible()));
	assert.equal(
		await page.getByRole('button', { name: 'Ajouter une compétence', exact: true }).count(),
		0
	);
	await page.locator('.text-subject button').click();
	await page.getByRole('dialog').waitFor();
	assert.equal(await page.getByLabel('Nom', { exact: true }).inputValue(), '');
	await page.getByRole('button', { name: 'Annuler', exact: true }).click();
	assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.setViewportSize({ width: 1440, height: 1100 });
	await page.getByRole('button', { name: 'M Raisonner et démontrer', exact: true }).waitFor();
	await page.locator('.graph-space canvas').waitFor({ state: 'visible' });
	const mobilePage = await context.newPage();
	mobilePage.on('pageerror', (error) => errors.push(error.message));
	await mobilePage.setViewportSize({ width: 390, height: 844 });
	await mobilePage.addInitScript(() => {
		window.__curriculumGlCalls = 0;
		const original = HTMLCanvasElement.prototype.getContext;
		HTMLCanvasElement.prototype.getContext = function (kind, ...options) {
			if (kind === 'webgl2' || kind === 'webgl') {
				window.__curriculumGlCalls++;
				return null;
			}
			return original.call(this, kind, ...options);
		};
	});
	await mobilePage.goto(`${origin}/curricula`);
	await mobilePage.locator('.text-node').first().waitFor();
	assert.equal(await mobilePage.evaluate(() => window.__curriculumGlCalls), 0);
	assert.equal(
		await mobilePage.getByRole('button', { name: 'Vue graphique', exact: true }).count(),
		0
	);
	await mobilePage.close();
	await page.getByRole('button', { name: 'Nouveau référentiel', exact: true }).click();
	assert.equal(await page.getByLabel('Filière', { exact: true }).count(), 0);
	await page.getByLabel('Nom du référentiel').fill('PCSI / PC');
	await page.getByLabel('Description', { exact: true }).fill('Programme de deux années');
	await page.locator('.subject-choice').filter({ hasText: 'Mathématiques' }).click();
	await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
	await page.getByRole('dialog').waitFor({ state: 'detached' });
	await page.waitForFunction(
		() => document.querySelector('[aria-label="Référentiel"]').value === '3'
	);
	assert.equal(catalog.curricula.at(-1).description, 'Programme de deux années');
	// Exercise the reader UI and a device without WebGL using the same synthetic catalogue.
	user.roles = ['kholleur'];
	user.permissions = ['kholleur.access', 'curricula.read'];
	catalog.can_manage = false;
	catalog.subjects.forEach((subject) => (subject.can_edit = false));
	const reader = await context.newPage();
	reader.on('pageerror', (error) => errors.push(error.message));
	await reader.addInitScript(() => {
		const original = HTMLCanvasElement.prototype.getContext;
		HTMLCanvasElement.prototype.getContext = function (kind, ...options) {
			return kind === 'webgl2' || kind === 'webgl'
				? null
				: original.call(this, kind, ...options);
		};
	});
	await reader.goto(`${origin}/curricula`);
	await reader.locator('.text-subject h3').first().waitFor();
	assert.equal(await reader.locator('.text-subject button').count(), 0);
	await reader.locator('.text-node').first().waitFor();
	assert.equal(await reader.getByRole('button', { name: 'Nouveau référentiel' }).count(), 0);
	assert.equal(await reader.getByRole('button', { name: 'Compétence racine' }).count(), 0);
	await reader.locator('.text-node').first().click();
	assert.ok(await reader.getByLabel('Nom', { exact: true }).isDisabled());
	assert.deepEqual(errors, []);
	console.log(
		'Browser: expansion, editing, subject/programme switching, mobile and reduced motion passed.'
	);
} finally {
	await browser?.close();
	await vite.close();
	await new Promise((resolve) => backend.close(resolve));
}
