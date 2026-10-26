/** Optional real-browser checks; invoked only from the guarded disposable HTTP journey. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

/** Exercise course reading/editing at desktop/mobile sizes using only synthetic accounts. */
export async function courseBrowserJourney({
	base,
	origin,
	teacherSession,
	studentSession,
	courseId,
	revokeCreator
}) {
	const browser = await chromium.launch({
		channel: process.env.BFF_BROWSER_CHANNEL || 'msedge',
		headless: true
	});
	try {
		const context = await browser.newContext({
			viewport: { width: 1440, height: 1000 },
			locale: 'fr-FR'
		});
		await context.route(`${origin}/**`, async (route) => {
			const url = new URL(route.request().url());
			const response = await route.fetch({
				url: base + url.pathname + url.search,
				headers: await route.request().allHeaders()
			});
			await route.fulfill({ response });
		});
		await context.addCookies([
			{
				name: 'sophikron_session_dev',
				value: teacherSession,
				url: origin,
				httpOnly: true,
				sameSite: 'Lax'
			}
		]);
		const page = await context.newPage();
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto(`${origin}/lessons`);
		const courseCard = page.locator('.course-card').filter({
			has: page.getByRole('heading', { name: 'Sciences et découvertes', exact: true })
		});
		await courseCard.waitFor();
		assert.equal(await page.getByRole('search').count(), 0);
		assert.equal(await courseCard.locator('.course-team .role-teacher').count(), 1);
		assert.equal(await courseCard.locator('.course-team a').count(), 0);
		await courseCard
			.getByRole('link', { name: 'Sciences et découvertes', exact: true })
			.click();
		await page.getByText('Mode lecture', { exact: true }).waitFor();
		await page.getByRole('button', { name: 'Statistiques du cours', exact: true }).click();
		await page.locator('.statistics-panel[aria-busy="false"]').waitFor();
		assert.equal(await page.locator('.statistics-grid .stat-card').count(), 3);
		assert.equal(
			await page.getByRole('heading', { name: 'Connexions', exact: true }).count(),
			0
		);
		await page.getByRole('button', { name: 'Statistiques du cours', exact: true }).click();
		assert.equal(
			await page.getByRole('button', { name: 'Ajouter une section', exact: true }).count(),
			0
		);
		assert.ok(await page.getByText('HIDDEN-COURSE-BODY', { exact: true }).isVisible());
		await page.getByRole('button', { name: 'Modifier le cours', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une section', exact: true }).click();
		const dialog = page.locator('dialog');
		await dialog.getByLabel('Titre', { exact: true }).fill('Explorer ensemble');
		assert.equal(await dialog.getByRole('combobox').count(), 0);
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		const section = page
			.locator('.lesson-section')
			.filter({ has: page.getByRole('heading', { name: 'Explorer ensemble', exact: true }) });
		await section.getByRole('button', { name: 'Texte', exact: true }).click();
		const textarea = dialog.getByLabel('Texte', { exact: true });
		await textarea.fill('Un mot');
		await textarea.evaluate((input) => {
			input.focus();
			input.setSelectionRange(3, 6);
		});
		await dialog.getByRole('button', { name: 'Gras', exact: true }).click();
		await dialog.getByRole('button', { name: 'Italique', exact: true }).click();
		await dialog.getByRole('button', { name: 'Couleur', exact: true }).click();
		assert.equal(await textarea.inputValue(), 'Un ==***mot***==');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.ok(await section.locator('.bold.italic.colored').isVisible());
		assert.equal(await section.locator('.eyebrow').count(), 0);
		await page
			.getByRole('navigation', { name: 'Sommaire du cours' })
			.getByRole('link', { name: 'Explorer ensemble', exact: true })
			.click();
		assert.equal(new URL(page.url()).hash, '#' + (await section.getAttribute('id')));
		await section.getByRole('button', { name: 'Tableau', exact: true }).click();
		await dialog.getByLabel('Titre', { exact: true }).fill('Ressources organisées');
		await dialog.getByLabel('Nombre de lignes', { exact: true }).fill('2');
		await dialog
			.getByLabel('Titre de la colonne 1', { exact: true })
			.fill('Approche personnelle');
		await dialog.getByRole('button', { name: 'Ajouter une colonne', exact: true }).click();
		await dialog
			.getByLabel('Titre de la colonne 2', { exact: true })
			.fill('Ressources complémentaires');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		const resourceTable = section.locator('.resource-table');
		assert.equal(await resourceTable.locator('tbody tr').count(), 2);
		assert.equal(
			await resourceTable.getByText('Cellule vide · ligne 1', { exact: true }).count(),
			2
		);
		for (let column = 3; column <= 6; column += 1) {
			await section.getByLabel('Titre de la nouvelle colonne').fill(`Ressource ${column}`);
			await section.getByRole('button', { name: 'Ajouter une colonne', exact: true }).click();
			await resourceTable
				.getByLabel(`Titre de la colonne ${column}`, { exact: true })
				.waitFor();
		}
		await resourceTable
			.locator('tbody td')
			.first()
			.getByRole('button', { name: 'Texte', exact: true })
			.click();
		await dialog.getByLabel('Texte', { exact: true }).fill('Ressource privée du tableau');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await section
			.getByRole('button', { name: 'Modifier Explorer ensemble', exact: true })
			.click();
		await dialog.getByRole('radio', { name: 'Équipe uniquement', exact: true }).check();
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await section.getByRole('button', { name: 'Document', exact: true }).last().click();
		await page.waitForFunction(
			() => !document.querySelector('dialog input[type="file"]')?.disabled
		);
		await dialog.getByLabel('Choisir un fichier', { exact: true }).setInputFiles({
			name: 'original.py',
			mimeType: 'text/plain',
			buffer: Buffer.alloc(1048577, 'x')
		});
		assert.equal(await dialog.getByLabel('Nom affiché dans le cours').inputValue(), 'original');
		await dialog.getByLabel('Nom affiché dans le cours').fill('Le nom pédagogique choisi');
		assert.ok(
			await dialog
				.getByText('Ce fichier dépasse la taille autorisée.', { exact: true })
				.isVisible()
		);
		assert.ok(
			await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).isDisabled()
		);
		page.once('dialog', (confirmation) => confirmation.accept());
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		let embeddedReferrer = null;
		await context.route('https://www.youtube-nocookie.com/**', async (route) => {
			embeddedReferrer = (await route.request().allHeaders()).referer;
			await route.fulfill({
				contentType: 'text/html; charset=utf-8',
				body: '<p>Lecteur de vérification</p>'
			});
		});
		await section.getByRole('button', { name: 'Vidéo', exact: true }).last().click();
		await dialog.getByLabel('Titre facultatif', { exact: true }).fill('Vidéo du cours');
		await dialog
			.getByLabel('Lien YouTube', { exact: true })
			.fill('https://youtu.be/abcdefghijk');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(await section.locator('iframe').count(), 0);
		assert.equal(await section.getByRole('link', { name: /Ouvrir sur YouTube/ }).count(), 0);
		await section.getByRole('button', { name: 'Lire Vidéo du cours', exact: true }).click();
		await page
			.frameLocator('iframe')
			.getByText('Lecteur de vérification', { exact: true })
			.waitFor();
		assert.equal(embeddedReferrer, origin + '/');
		await page.getByRole('button', { name: 'Accès et collaborateurs', exact: true }).click();
		await dialog
			.getByLabel('Ajouter un enseignant ou un khôlleur', { exact: true })
			.fill('Camille');
		await dialog
			.locator('#collaborator-candidates')
			.getByRole('button', { name: /^Ajouter / })
			.first()
			.click();
		await dialog.getByText('Collaborateur', { exact: true }).waitFor();
		await page.keyboard.press('Escape');
		await page.getByRole('button', { name: 'Revenir à la lecture', exact: true }).click();
		const screenshots = process.env.BFF_SCREENSHOTS_DIRECTORY;
		if (screenshots) {
			await mkdir(screenshots, { recursive: true });
			await page.screenshot({ path: `${screenshots}/course-desktop.png`, fullPage: true });
		}
		await page.setViewportSize({ width: 390, height: 844 });
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		const scroller = section.locator('.table-container');
		assert.ok(await scroller.evaluate((element) => element.scrollWidth > element.clientWidth));
		assert.ok(await resourceTable.locator('thead').isVisible());
		await scroller.focus();
		await page.keyboard.press('ArrowRight');
		await page.waitForFunction(() => document.querySelector('.table-container').scrollLeft > 0);
		if (screenshots)
			await page.screenshot({ path: `${screenshots}/course-mobile.png`, fullPage: true });
		await page.goto(`${origin}/lessons`);
		await courseCard.waitFor();
		assert.equal(await courseCard.locator('.course-team .role-teacher').count(), 2);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await courseCard
			.getByRole('link', { name: 'Sciences et découvertes', exact: true })
			.click();
		await revokeCreator();
		await page.getByRole('button', { name: 'Modifier le cours', exact: true }).click();
		await page
			.getByRole('button', { name: 'Modifier le cours', exact: true })
			.waitFor({ state: 'hidden' });
		assert.equal(await page.getByText('Mode lecture', { exact: true }).count(), 0);
		await context.clearCookies();
		await context.addCookies([
			{
				name: 'sophikron_session_dev',
				value: studentSession,
				url: origin,
				httpOnly: true,
				sameSite: 'Lax'
			}
		]);
		await page.goto(`${origin}/lessons/${courseId}`);
		await page.getByRole('heading', { name: 'Le programme à venir', exact: true }).waitFor();
		await page.getByRole('button', { name: 'Le programme à venir', exact: true }).click();
		assert.ok(await page.getByText('HIDDEN-COURSE-BODY', { exact: true }).isVisible());
		assert.equal(
			await page.getByText('Ressource privée du tableau', { exact: true }).count(),
			0
		);
		assert.equal(
			await page.getByRole('button', { name: 'Modifier le cours', exact: true }).count(),
			0
		);
		assert.ok(
			await page
				.getByRole('heading', { name: 'Découvrir dès maintenant', exact: true })
				.isVisible()
		);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		if (screenshots)
			await page.screenshot({
				path: `${screenshots}/course-student-mobile.png`,
				fullPage: true
			});
		assert.deepEqual(errors, []);
		await context.close();
		console.log(
			'Course browser journey passed: editing, combined formatting, collaborators, mobile layout, filtered reading and live role revocation.'
		);
	} finally {
		await browser.close();
	}
}

export async function browserJourney({
	base,
	origin,
	adminSession,
	teacherSession,
	promotion,
	student,
	teacher
}) {
	const browser = await chromium.launch({
		channel: process.env.BFF_BROWSER_CHANNEL || 'msedge',
		headless: true
	});
	const errors = [];
	try {
		const context = await browser.newContext({
			viewport: { width: 1440, height: 1000 },
			locale: 'fr-FR'
		});
		// Publish disposable ports through the configured public origin, just like a host proxy.
		await context.route(`${origin}/**`, async (route) => {
			const url = new URL(route.request().url());
			if (
				url.pathname === '/dashboard/data' &&
				url.searchParams.get('resource') === 'communes'
			) {
				if (url.searchParams.get('q') === 'Panne') {
					await route.fulfill({
						status: 503,
						json: { message: 'Service des communes indisponible.' }
					});
				} else
					await route.fulfill({
						json: [{ code: '44109', nom: 'Nantes', codesPostaux: ['44000'] }]
					});
				return;
			}
			const response = await route.fetch({
				url: base + url.pathname + url.search,
				headers: await route.request().allHeaders()
			});
			await route.fulfill({ response });
		});
		await context.addCookies([
			{
				name: 'sophikron_session_dev',
				value: adminSession,
				url: origin,
				httpOnly: true,
				sameSite: 'Lax'
			}
		]);
		const page = await context.newPage();
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto(`${origin}/dashboard`);
		await page.getByText('Les comptes', { exact: true }).waitFor();
		await page.getByText('Promotions et matières', { exact: true }).waitFor();
		assert.equal(await page.locator('.statistics-grid .stat-card').count(), 6);
		const connections = page
			.locator('.stat-card')
			.filter({ has: page.getByRole('heading', { name: 'Connexions', exact: true }) });
		assert.equal(await connections.locator('polyline').count(), 3);
		await connections.getByRole('button', { name: 'Tentatives', exact: true }).click();
		assert.equal(await connections.locator('polyline').count(), 2);
		assert.equal(
			await connections
				.getByRole('button', { name: 'Tentatives', exact: true })
				.getAttribute('aria-pressed'),
			'false'
		);
		await connections.getByRole('button', { name: 'Comptes uniques', exact: true }).click();
		await connections.getByRole('button', { name: 'Réussies', exact: true }).click();
		assert.ok(await connections.getByRole('status').isVisible());
		for (const label of ['Comptes uniques', 'Réussies', 'Tentatives'])
			await connections.getByRole('button', { name: label, exact: true }).click();
		await page
			.getByRole('group', { name: 'Période des statistiques' })
			.getByRole('button', { name: 'Jour', exact: true })
			.click();
		await page.locator('.statistics-panel[aria-busy="false"]').waitFor();
		assert.equal(await connections.locator('polyline').count(), 3);
		await page
			.getByRole('group', { name: 'Période des statistiques' })
			.getByRole('button', { name: 'Semaine', exact: true })
			.click();
		await page.locator('.statistics-panel[aria-busy="false"]').waitFor();
		await page.locator('.event-row').first().waitFor();
		assert.ok((await page.locator('.event-row').count()) <= 15);
		const journal = page.locator('.event-panel');
		const eventType = page.getByLabel('Type d’événement', { exact: true });
		const eventOrder = page.getByLabel('Ordre chronologique', { exact: true });
		await eventType
			.locator('option[value="user.profile_updated"]')
			.waitFor({ state: 'attached' });
		assert.equal(await eventType.inputValue(), '');
		assert.equal(await eventOrder.inputValue(), 'desc');
		await eventType.selectOption('user.profile_updated');
		await journal.locator('.event-list[aria-busy="false"]').waitFor();
		assert.equal(await journal.locator('.event-row').count(), 15);
		const firstIds = await journal
			.locator('.event-row')
			.evaluateAll((rows) => rows.map((row) => row.dataset.eventId));
		await journal.getByRole('button', { name: 'Page suivante du journal' }).click();
		await journal.getByRole('status').filter({ hasText: 'Page 2' }).waitFor();
		const secondIds = await journal
			.locator('.event-row')
			.evaluateAll((rows) => rows.map((row) => row.dataset.eventId));
		assert.equal(new Set([...firstIds, ...secondIds]).size, 30);
		await journal.getByRole('button', { name: 'Page suivante du journal' }).click();
		await journal.getByRole('status').filter({ hasText: 'Page 3' }).waitFor();
		assert.equal(await journal.locator('.event-row').count(), 2);
		assert.ok(
			await journal.getByRole('button', { name: 'Page suivante du journal' }).isDisabled()
		);
		await journal.getByRole('button', { name: 'Page précédente du journal' }).click();
		await journal.getByRole('status').filter({ hasText: 'Page 2' }).waitFor();
		await eventOrder.selectOption('asc');
		await journal.locator('.event-list[aria-busy="false"]').waitFor();
		await journal.getByRole('status').filter({ hasText: 'Page 1' }).waitFor();
		const times = await journal
			.locator('time')
			.evaluateAll((items) => items.map((item) => Date.parse(item.dateTime)));
		assert.ok(times.every((time, index) => index === 0 || times[index - 1] <= time));
		await eventType.selectOption('user.created');
		await journal.locator('.event-list[aria-busy="false"]').waitFor();
		assert.ok(
			await journal.getByRole('button', { name: 'Page suivante du journal' }).isDisabled()
		);
		await journal.locator('a.role-badge').first().click();
		await page.locator('.profile-page-hero').waitFor();
		assert.ok(new URL(page.url()).searchParams.has('id'));
		await page.goto(`${origin}/dashboard`);
		await eventType.locator('option[value="promotion.created"]').waitFor({ state: 'attached' });
		await eventType.selectOption('promotion.created');
		await journal.locator('.event-list[aria-busy="false"]').waitFor();
		await journal.locator('a.promotion-tag').first().click();
		await page
			.getByRole('dialog')
			.getByRole('heading', { name: 'Modifier la promotion', exact: true })
			.waitFor();
		await page.keyboard.press('Escape');
		await page.goto(`${origin}/dashboard`);
		await journal.locator('.event-row').first().waitFor();
		const screenshots = process.env.BFF_SCREENSHOTS_DIRECTORY;
		if (screenshots) {
			await mkdir(screenshots, { recursive: true });
			await page.screenshot({ path: `${screenshots}/dashboard-desktop.png`, fullPage: true });
		}
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Promotions', exact: true })
			.click();
		await page.getByRole('button', { name: 'Nouvelle promotion', exact: true }).click();
		const dialog = page.getByRole('dialog');
		await dialog.getByLabel('Identifiant de la promotion').fill('PCSI');
		await dialog.getByLabel('Année', { exact: true }).fill('2027');
		assert.ok(await dialog.locator('form').evaluate((form) => form.reportValidity()));
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await Promise.race([
			dialog.waitFor({ state: 'hidden' }),
			dialog
				.getByRole('alert')
				.waitFor()
				.then(async () => {
					throw new Error(
						`Promotion save failed: ${await dialog.getByRole('alert').textContent()}`
					);
				})
		]);
		await page.getByRole('button', { name: /2027.*PCSI/ }).waitFor();
		await page.goto(origin + '/dashboard?promotion=' + promotion.id);
		const kholleur = await page.evaluate(async () => {
			const response = await fetch('/dashboard/command', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					command: 'createUser',
					data: {
						first_name: 'Camille',
						last_name: 'Colleur',
						email: 'browser-kholleur@example.org',
						roles: ['kholleur']
					}
				})
			});
			if (!response.ok) throw new Error('Could not create the synthetic kholleur');
			return response.json();
		});
		assert.deepEqual(
			await page.getByLabel('Filtrer par rôle').locator('option').allTextContents(),
			['Tous les rôles', 'Élèves', 'Professeurs']
		);
		await page.getByRole('button', { name: 'Ajouter des membres', exact: true }).click();
		assert.deepEqual(
			await dialog.getByLabel('Type de compte').locator('option').allTextContents(),
			['Élèves', 'Enseignants']
		);
		await dialog.getByLabel('Type de compte').selectOption('teaching');
		await dialog.getByLabel('Rechercher des comptes à ajouter').fill(kholleur.username);
		await dialog
			.locator('.member-choice')
			.filter({ hasText: kholleur.username })
			.getByRole('checkbox')
			.check();
		await dialog.getByRole('button', { name: 'Ajouter la sélection', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByLabel('Filtrer par rôle').selectOption('teaching');
		await page.locator('.account-row').filter({ hasText: kholleur.username }).waitFor();
		assert.equal(
			await page.locator('.account-row').filter({ hasText: kholleur.username }).count(),
			1
		);
		await page.getByLabel('Filtrer par rôle').selectOption('');
		await page.getByRole('button', { name: 'Archiver', exact: true }).click();
		const archiveStudents = page.getByRole('checkbox', { name: /Archiver également/ });
		await archiveStudents.waitFor();
		assert.equal(await archiveStudents.isChecked(), false);
		await archiveStudents.check();
		await page
			.getByRole('alert')
			.filter({ hasText: 'cette action désactive la connexion' })
			.waitFor();
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		await page.getByRole('button', { name: 'Archiver', exact: true }).click();
		await archiveStudents.waitFor();
		assert.equal(await archiveStudents.isChecked(), false);
		await archiveStudents.check();
		await page.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page.getByRole('button', { name: 'Réactiver', exact: true }).waitFor();
		await page.getByRole('button', { name: 'Réactiver', exact: true }).click();
		await page.getByRole('alert').filter({ hasText: '1 compte restera désactivé' }).waitFor();
		await page.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page.getByRole('button', { name: 'Archiver', exact: true }).waitFor();

		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Comptes', exact: true })
			.click();
		await page.getByRole('button', { name: 'Créer un compte', exact: true }).click();
		const creationRoles = dialog.getByRole('group', { name: 'Rôles du compte', exact: true });
		await creationRoles.getByRole('checkbox', { name: 'Élève', exact: true }).uncheck();
		await creationRoles.getByRole('checkbox', { name: 'Administrateur', exact: true }).check();
		assert.equal(await dialog.locator('.promotion-checks').count(), 0);
		await creationRoles.getByRole('checkbox', { name: 'Khôlleur', exact: true }).check();
		assert.ok(await dialog.locator('.promotion-checks').isVisible());
		await creationRoles
			.getByRole('checkbox', { name: 'Administrateur', exact: true })
			.uncheck();
		await creationRoles.getByRole('checkbox', { name: 'Khôlleur', exact: true }).uncheck();
		await creationRoles.getByRole('checkbox', { name: 'Élève', exact: true }).check();
		await dialog.getByLabel('Prénom', { exact: true }).fill('Élodie');
		await dialog.getByLabel('Nom', { exact: true }).fill('Roy');
		await dialog.getByLabel('Adresse email', { exact: true }).fill('browser@example.org');
		await dialog.getByRole('button', { name: 'Créer le compte', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Compte créé', exact: true }).waitFor();
		await dialog.getByRole('button', { name: 'Préparer l’invitation', exact: true }).click();
		await dialog.getByText('Invitation prête à partager', { exact: true }).waitFor();
		await dialog.getByRole('button', { name: 'Créer un autre compte', exact: true }).click();
		assert.equal(await dialog.getByLabel('Prénom', { exact: true }).inputValue(), '');
		await page.keyboard.press('Escape');
		await dialog.waitFor({ state: 'hidden' });
		await page
			.getByRole('textbox', { name: 'Rechercher un compte', exact: true })
			.fill(student.username);
		await page.locator('.account-row').filter({ hasText: student.username }).click();
		await dialog.getByRole('heading', { name: 'Valentin Burgaud', exact: true }).waitFor();
		await dialog.getByRole('link', { name: 'Voir la fiche complète', exact: true }).click();
		await page.getByRole('heading', { name: 'Valentin Burgaud', exact: true }).waitFor();
		await page.getByLabel('Ville et code postal', { exact: true }).fill('Nant');
		await page.getByRole('button', { name: 'Nantes 44000', exact: true }).click();
		assert.equal(
			await page.getByLabel('Ville et code postal', { exact: true }).inputValue(),
			'Nantes 44000'
		);
		await page.getByRole('button', { name: 'Retirer la commune', exact: true }).click();
		await page.getByLabel('Ville et code postal', { exact: true }).fill('Panne');
		await page.getByText('Service des communes indisponible.', { exact: false }).waitFor();
		await page.getByRole('button', { name: 'Annuler la recherche', exact: true }).click();
		await page.getByLabel('Téléphone', { exact: true }).fill('06 12 34 56 78');
		await page.getByLabel('Établissement précédent', { exact: true }).fill('Lycée Exemple');
		await page.getByLabel('Année d’obtention', { exact: true }).fill('2024');
		await page.getByLabel('Moyenne générale /20', { exact: true }).fill('15.5');
		await page.getByRole('button', { name: 'Ajouter une option', exact: true }).click();
		await page.getByLabel('Option 1', { exact: true }).fill('Mathématiques');
		await page.getByLabel('Note /20', { exact: true }).fill('0');
		await page.getByLabel('Prénom du référent', { exact: true }).fill('Marie');
		await page.getByLabel('Nom du référent', { exact: true }).fill('Roy');
		await page.getByLabel('Téléphone du référent', { exact: true }).fill('01 23 45 67 89');
		await page.getByRole('link', { name: 'Retour aux comptes', exact: true }).click();
		await dialog
			.getByRole('heading', { name: 'Modifications non enregistrées', exact: true })
			.waitFor();
		await dialog.getByRole('button', { name: 'Rester sur la fiche', exact: true }).click();
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
		await page.locator('form[aria-busy="false"]').waitFor();
		assert.ok(
			await page
				.locator('.profile-save-bar [role="status"]')
				.evaluate((element) => document.activeElement === element)
		);
		assert.equal(
			await page.getByLabel('Téléphone', { exact: true }).inputValue(),
			'+33612345678'
		);
		const roleSelector = page.getByRole('group', { name: 'Rôles du compte', exact: true });
		const chooseRoles = async (roles) => {
			for (const label of ['Élève', 'Khôlleur', 'Enseignant', 'Administrateur'])
				await roleSelector
					.getByRole('checkbox', { name: label, exact: true })
					.setChecked(roles.includes(label));
		};
		assert.ok(
			await roleSelector.getByRole('checkbox', { name: 'Élève', exact: true }).isChecked()
		);
		await roleSelector.getByRole('checkbox', { name: 'Enseignant', exact: true }).check();
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await page.getByRole('alert').filter({ hasText: 'Le rôle Élève est exclusif' }).waitFor();
		assert.equal(await page.locator('dialog[open]').count(), 0);
		await chooseRoles(['Enseignant', 'Administrateur']);
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Confirmer le changement des accès' }).waitFor();
		assert.ok(
			(await dialog.getByRole('alert').textContent())
				.replace(/\s+/g, ' ')
				.includes('Valentin Burgaud')
		);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.ok(
			await roleSelector
				.getByRole('checkbox', { name: 'Administrateur', exact: true })
				.isChecked()
		);
		assert.equal(await page.locator('.profile-page-hero .role-admin').count(), 0);
		for (const roles of [
			['Khôlleur', 'Enseignant', 'Administrateur'],
			['Khôlleur', 'Enseignant'],
			['Khôlleur', 'Administrateur'],
			['Élève']
		]) {
			await chooseRoles(roles);
			await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
			await dialog
				.getByRole('heading', { name: 'Confirmer le changement des accès' })
				.waitFor();
			await dialog
				.getByRole('button', { name: 'Confirmer et enregistrer', exact: true })
				.click();
			await dialog.waitFor({ state: 'hidden' });
			await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
			await page.locator('form[aria-busy="false"]').waitFor();
			if (screenshots && roles.length === 3)
				await page.screenshot({ path: screenshots + '/roles-desktop.png', fullPage: true });
			const header = page.locator('.profile-page-hero');
			for (const [label, css] of [
				['Administrateur', 'admin'],
				['Enseignant', 'teacher'],
				['Khôlleur', 'kholleur']
			])
				assert.equal(
					await header.locator('.role-' + css).count(),
					roles.includes(label) ? 1 : 0
				);
		}
		await page.reload();
		assert.ok(
			await roleSelector.getByRole('checkbox', { name: 'Élève', exact: true }).isChecked()
		);
		await page.goto(`${origin}/dashboard`);
		await eventType
			.locator('option[value="user.roles_updated"]')
			.waitFor({ state: 'attached' });
		await eventType.selectOption('user.roles_updated');
		await journal.locator('.event-list[aria-busy="false"]').waitFor();
		assert.equal(await journal.locator('.role-transition').count(), 4);
		assert.ok(await journal.locator('.role-transition .role-student').first().isVisible());
		assert.ok(await journal.locator('.role-transition .role-admin').first().isVisible());
		assert.ok(await journal.locator('.role-transition .role-teacher').first().isVisible());
		await page.goto(`${origin}/dashboard/user?id=${student.id}`);
		if (screenshots)
			await page.screenshot({
				path: `${screenshots}/student-profile-desktop.png`,
				fullPage: true
			});
		await page.getByRole('link', { name: 'Retour aux comptes', exact: true }).click();
		await page.setViewportSize({ width: 390, height: 844 });
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Vue d’ensemble', exact: true })
			.click();
		await page.getByText('Les comptes', { exact: true }).waitFor();
		assert.ok(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		);
		if (screenshots)
			await page.screenshot({ path: `${screenshots}/dashboard-mobile.png`, fullPage: true });
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Comptes', exact: true })
			.click();
		await page.getByRole('button', { name: 'Créer un compte', exact: true }).click();
		assert.ok(
			await dialog.evaluate(
				(element) => element.getBoundingClientRect().width <= window.innerWidth
			)
		);
		await page.keyboard.press('Escape');

		await page.goto(origin + '/dashboard');
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Matières', exact: true })
			.click();
		await page.waitForURL('**/dashboard?tab=subjects');
		await page.getByRole('button', { name: 'Nouvelle matière', exact: true }).click();
		await dialog.getByLabel('Nom de la matière', { exact: true }).fill('Matière navigateur');
		await dialog
			.getByRole('group', { name: 'Icône', exact: true })
			.getByRole('radio', { name: 'Sciences', exact: true })
			.check();
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.locator('.subject-card').filter({ hasText: 'Matière navigateur' }).click();
		await page.getByRole('button', { name: 'Modifier', exact: true }).click();
		await dialog.getByLabel('Nom de la matière', { exact: true }).fill('Matière corrigée');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.goto(origin + '/dashboard/user?id=' + teacher.id);
		const assignedSubjects = page.getByRole('group', {
			name: 'Matières affectées',
			exact: true
		});
		await assignedSubjects
			.getByRole('checkbox', { name: 'Matière corrigée', exact: true })
			.check();
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
		await page.locator('form[aria-busy="false"]').waitFor();

		await page.goto(origin + '/dashboard?tab=team');
		const teamSubject = page
			.locator('.team-subject')
			.filter({ has: page.getByRole('heading', { name: 'Matière corrigée', exact: true }) });
		await teamSubject.getByRole('link', { name: 'Marie Dupont', exact: true }).waitFor();
		assert.equal(await teamSubject.locator('a.role-teacher').count(), 1);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await teamSubject.getByRole('link', { name: 'Marie Dupont', exact: true }).click();
		await assignedSubjects
			.getByRole('checkbox', { name: 'Matière corrigée', exact: true })
			.waitFor();
		await assignedSubjects
			.getByRole('checkbox', { name: 'Matière corrigée', exact: true })
			.uncheck();
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await dialog.getByRole('button', { name: 'Confirmer et enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
		await page.goto(origin + '/dashboard?tab=overview');
		await page
			.getByLabel('Type d’événement', { exact: true })
			.selectOption('user.subjects_updated');
		const assignments = page.locator('.event-row[data-event-type="user.subjects_updated"]');
		await assignments.filter({ hasText: 'Matières attribuées' }).waitFor();
		await assignments.filter({ hasText: 'Matières retirées' }).waitFor();
		assert.equal(
			await assignments
				.locator('.subject-badge')
				.filter({ hasText: 'Matière corrigée' })
				.count(),
			2
		);
		if (screenshots)
			await page.screenshot({
				path: screenshots + '/subject-journal-mobile.png',
				fullPage: true
			});
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Matières', exact: true })
			.click();
		await page.locator('.subject-card').filter({ hasText: 'Matière corrigée' }).click();
		await page.getByRole('button', { name: 'Archiver', exact: true }).click();
		await page.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page.getByLabel('État des matières').selectOption('false');
		await page.locator('.subject-card').filter({ hasText: 'Matière corrigée' }).waitFor();
		await page.getByRole('button', { name: 'Vue d’ensemble', exact: true }).click();
		await page.waitForURL('**/dashboard?tab=overview');
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Configuration', exact: true })
			.click();
		await page.waitForURL('**/dashboard?tab=configuration');

		await page.getByLabel('Nom du site', { exact: true }).fill('Lycée des sciences');
		await page
			.locator('#holiday-color')
			.locator('..')
			.getByLabel('Code couleur hexadécimal', { exact: true })
			.fill('#AA33CC');
		await page
			.getByLabel('Texte d’accueil', { exact: true })
			.fill('# Notre école\n**Bienvenue**');
		await page
			.getByRole('button', { name: 'Enregistrer la configuration', exact: true })
			.click();
		await page.getByRole('status').filter({ hasText: 'sans redémarrage' }).waitFor();
		assert.equal(new URL(page.url()).searchParams.get('tab'), 'configuration');
		assert.equal(await page.locator('.brand-name').textContent(), 'Lycée des sciences');
		for (const bar of ['Première année', 'Deuxième année']) {
			await page.getByRole('button', { name: 'Ajouter une timeline', exact: true }).click();
			await dialog.getByLabel('Intitulé', { exact: true }).fill(bar);
			await dialog.getByLabel('Début inclus', { exact: true }).fill('2026-09-01');
			await dialog.getByLabel('Fin incluse', { exact: true }).fill('2027-08-31');
			await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
			await dialog.waitFor({ state: 'hidden' });
		}
		for (const [name, start, end, kind] of [
			['Vacances communes', '2026-12-20', '2027-01-03', 'holiday'],
			['Vacances de printemps', '2027-04-10', '2027-04-25', 'holiday'],
			['Oraux du concours', '2027-05-10', '2027-05-12', 'oral']
		]) {
			await page.getByRole('button', { name: 'Ajouter un événement', exact: true }).click();
			await dialog.getByLabel('Intitulé', { exact: true }).fill(name);
			await dialog.getByLabel('Début inclus', { exact: true }).fill(start);
			await dialog.getByLabel('Fin incluse', { exact: true }).fill(end);
			await dialog.getByLabel('Type', { exact: true }).selectOption(kind);
			await dialog.getByLabel('Deuxième année', { exact: true }).check();
			if (kind === 'holiday') {
				assert.equal(
					await dialog.getByLabel('Code couleur hexadécimal', { exact: true }).count(),
					0
				);
				await dialog.getByText('Couleur commune aux vacances.', { exact: false }).waitFor();
				await dialog.getByLabel('Première année', { exact: true }).check();
			} else
				await dialog
					.getByLabel('Code couleur hexadécimal', { exact: true })
					.fill('#FF8800');
			await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
			await dialog.waitFor({ state: 'hidden' });
		}
		await page.goto(origin);
		await page.getByRole('heading', { name: 'Notre école', exact: true }).waitFor();
		assert.equal(await page.locator('.timeline-rail').count(), 2);
		assert.equal(await page.locator('.timeline-months > span').count(), 24);
		assert.equal(
			await page.locator('.calendar-legend').getByText('Vacances', { exact: true }).count(),
			1
		);
		assert.equal(await page.locator('.timeline-event').count(), 5);
		assert.equal(
			await page
				.locator('.calendar-legend')
				.getByText('Oraux du concours', { exact: true })
				.count(),
			1
		);
		const holidayColors = await page
			.locator('.timeline-event')
			.evaluateAll((elements) =>
				elements
					.filter((element) =>
						element.getAttribute('aria-label').includes('· Vacances ·')
					)
					.map((element) => element.style.getPropertyValue('--event-color'))
			);
		assert.deepEqual(holidayColors, ['#AA33CC', '#AA33CC', '#AA33CC', '#AA33CC']);
		if (screenshots) {
			await page.screenshot({ path: screenshots + '/timelines-mobile.png', fullPage: true });
			await page.setViewportSize({ width: 1440, height: 1000 });
			await page.screenshot({ path: screenshots + '/timelines-desktop.png', fullPage: true });
			await page.setViewportSize({ width: 390, height: 844 });
		}
		assert.ok(
			await page
				.locator('.calendar-overview')
				.evaluate(
					(element) =>
						element.compareDocumentPosition(document.querySelector('.home-hero')) &
						Node.DOCUMENT_POSITION_FOLLOWING
				)
		);
		await page.getByLabel('Informations sur Première année', { exact: true }).click();
		await page
			.getByText(/jours de cours restants/)
			.first()
			.waitFor();
		const event = page.locator('.timeline-event').first();
		await event.focus();
		assert.equal(
			await event.locator('.tip').evaluate((element) => getComputedStyle(element).visibility),
			'visible'
		);
		await page.getByLabel('Informations sur Première année', { exact: true }).click();
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await page.goto(`${origin}/dashboard/user?id=${kholleur.id}`);
		await page.getByRole('group', { name: 'Rôles du compte', exact: true }).waitFor();
		await page
			.getByRole('group', { name: 'Rôles du compte', exact: true })
			.getByRole('checkbox', { name: 'Khôlleur', exact: true })
			.uncheck();
		await page
			.getByRole('group', { name: 'Rôles du compte', exact: true })
			.getByRole('checkbox', { name: 'Administrateur', exact: true })
			.check();
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await dialog.getByText(/Ce compte perd son éligibilité aux promotions/).waitFor();
		await dialog.getByRole('button', { name: 'Confirmer et enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
		const remainingPromotions = await page.evaluate(async (id) => {
			const response = await fetch(`/dashboard/data?resource=userPromotions&id=${id}`);
			if (!response.ok) throw new Error('Could not verify automatic membership removal');
			return response.json();
		}, kholleur.id);
		assert.equal(remainingPromotions.total, 0);
		await context.clearCookies();
		await context.addCookies([
			{
				name: 'sophikron_session_dev',
				value: teacherSession,
				url: origin,
				httpOnly: true,
				sameSite: 'Lax'
			}
		]);
		await page.goto(`${origin}/dashboard`);
		await page.getByRole('button', { name: 'Mes statistiques', exact: true }).click();
		await page.locator('.statistics-panel[aria-busy="false"]').waitFor();
		assert.ok(
			await page.getByRole('heading', { name: 'Mes cours créés', exact: true }).isVisible()
		);
		assert.equal(
			await page.getByRole('heading', { name: 'Les comptes', exact: true }).count(),
			0
		);
		await page.getByRole('button', { name: 'Mes élèves', exact: true }).click();
		await page.locator('.account-row').filter({ hasText: student.username }).click();
		await dialog.getByRole('heading', { name: 'Valentin Burgaud', exact: true }).waitFor();
		assert.equal(
			await dialog.getByRole('button', { name: /Archiver|Réinitialiser|invitation/ }).count(),
			0
		);
		assert.equal(
			await page.getByRole('button', { name: 'Vue d’ensemble', exact: true }).count(),
			0
		);
		await dialog.getByRole('link', { name: 'Voir la fiche complète', exact: true }).click();
		await page.getByRole('heading', { name: 'Valentin Burgaud', exact: true }).waitFor();
		assert.ok(await page.getByLabel('Email', { exact: true }).isDisabled());
		assert.equal(
			await page.getByRole('group', { name: 'Rôles du compte', exact: true }).count(),
			0
		);
		assert.ok(await page.getByLabel('Téléphone', { exact: true }).isDisabled());
		await page
			.getByLabel('Projet, filière ou concours envisagés', { exact: true })
			.fill('École d’ingénieurs');
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		if (screenshots)
			await page.screenshot({
				path: `${screenshots}/student-profile-mobile.png`,
				fullPage: true
			});
		await page.goto(`${origin}/me`);
		if (screenshots)
			await page.screenshot({
				path: `${screenshots}/personal-page-mobile.png`,
				fullPage: true
			});
		await page.getByRole('button', { name: 'Mot de passe', exact: true }).click();
		await dialog
			.getByRole('heading', { name: 'Changer mon mot de passe', exact: true })
			.waitFor();
		await page.keyboard.press('Escape');
		assert.deepEqual(errors, []);
		await context.close();
		console.log(
			'Browser journey passed: desktop/mobile dashboard, modals, repeated creation, invitations and restricted teacher profiles.'
		);
	} finally {
		await browser.close();
	}
}
