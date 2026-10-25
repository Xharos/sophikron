/** Optional real-browser checks; invoked only from the guarded disposable HTTP journey. */
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

export async function browserJourney({ base, origin, adminSession, teacherSession, student }) {
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
		await page.getByText('Les promotions', { exact: true }).waitFor();
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
		await page
			.getByRole('navigation', { name: 'Navigation de l’espace de gestion' })
			.getByRole('button', { name: 'Comptes', exact: true })
			.click();
		await page.getByRole('button', { name: 'Créer un compte', exact: true }).click();
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
		const roleSelector = page.getByLabel('Rôle du compte', { exact: true });
		assert.equal(await roleSelector.inputValue(), 'user');
		await roleSelector.selectOption('teacher_admin');
		await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Confirmer le changement de rôle' }).waitFor();
		assert.ok(
			(await dialog.getByRole('alert').textContent())
				.replace(/\s+/g, ' ')
				.includes('Valentin Burgaud')
		);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(await roleSelector.inputValue(), 'teacher_admin');
		assert.equal(await page.locator('.profile-page-hero .role-admin').count(), 0);
		for (const choice of ['teacher_admin', 'teacher', 'admin', 'user']) {
			await roleSelector.selectOption(choice);
			await page.getByRole('button', { name: 'Enregistrer la fiche', exact: true }).click();
			await dialog
				.getByRole('heading', { name: 'Confirmer le changement de rôle' })
				.waitFor();
			await dialog
				.getByRole('button', { name: 'Confirmer et enregistrer', exact: true })
				.click();
			await dialog.waitFor({ state: 'hidden' });
			await page.getByText('Fiche enregistrée.', { exact: true }).waitFor();
			await page.locator('form[aria-busy="false"]').waitFor();
			assert.equal(await roleSelector.inputValue(), choice);
			const header = page.locator('.profile-page-hero');
			assert.equal(
				await header.locator('.role-admin').count(),
				choice.includes('admin') ? 1 : 0
			);
			assert.equal(
				await header.locator('.role-teacher').count(),
				choice.includes('teacher') ? 1 : 0
			);
		}
		await page.reload();
		assert.equal(await roleSelector.inputValue(), 'user');
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
		assert.equal(await page.getByLabel('Rôle du compte', { exact: true }).count(), 0);
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
