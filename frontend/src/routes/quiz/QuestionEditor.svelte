<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { untrack } from 'svelte';
	import type { QuizEdit, QuizRule, QuizSubject } from '#lib/quiz';
	import { quizAction } from './api';
	import QuestionPreview from './QuestionPreview.svelte';

	import FileDropzone from '#lib/components/lessons/FileDropzone.svelte';

	let { subject, question }: { subject: QuizSubject; question: QuizEdit | null } = $props();
	const subjectParams = $derived({ subjectId: String(subject.id) });
	const initial = untrack(() => question);
	const initialRule = initial?.rule;
	let title = $state(initial?.title ?? '');
	let statement = $state(initial?.statement ?? '');
	let prompt = $state(initial?.prompt ?? '');
	let kind = $state<QuizRule['kind']>(initialRule?.kind ?? 'choice');
	let options = $state(initialRule?.kind === 'choice' ? [...initialRule.options] : ['', '']);
	let correct = $state(initialRule?.kind === 'choice' ? [...initialRule.correct] : []);
	let expected = $state(initialRule?.kind === 'number' ? initialRule.expected : '');
	let tolerance = $state(initialRule?.kind === 'number' ? initialRule.tolerance : '');
	let accepted = $state(initialRule?.kind === 'text' ? initialRule.accepted.join('\n') : '');
	let image = $state(initial?.image ?? null);
	let imageAlt = $state(initial?.image_alt ?? '');
	let competencyIds = $state([...(initial?.competency_ids ?? [])]);
	let imageFile = $state<File | null>(null);
	let tab = $state<'write' | 'preview'>('write');
	let competencyQuery = $state('');
	const pageId = $props.id();
	const matches = $derived(
		subject.competencies.filter((item) =>
			(item.name + ' ' + item.curriculum)
				.toLocaleLowerCase()
				.includes(competencyQuery.trim().toLocaleLowerCase())
		)
	);
	const shownCompetencies = $derived(matches.slice(0, 5));
	const preview = $derived({
		id: question?.id ?? 0,
		version: question?.version ?? 0,
		archived: question?.archived ?? false,
		title: title.trim(),
		statement: statement.trim(),
		prompt: prompt.trim(),
		kind,
		image,
		image_alt: imageAlt.trim(),
		options: kind === 'choice' ? options.map((value) => value.trim()) : []
	});

	function toggleCompetency(id: number, checked: boolean): void {
		competencyIds = checked
			? [...competencyIds, id]
			: competencyIds.filter((value) => value !== id);
	}
	let failure = $state('');
	let imageFailure = $state('');
	let reading = $state(false);
	let busy = $state(false);

	function removeOption(index: number): void {
		options.splice(index, 1);
		correct = correct
			.filter((value) => value !== index)
			.map((value) => (value > index ? value - 1 : value));
	}

	function upload(file: File): void {
		imageFailure = '';
		const name = file.name.toLowerCase();
		const format =
			file.type ||
			(name.endsWith('.png') ? 'image/png' : /\.jpe?g$/.test(name) ? 'image/jpeg' : '');
		if (!['image/png', 'image/jpeg'].includes(format)) {
			imageFailure = 'Image : seuls les formats PNG et JPEG sont acceptés.';
			return;
		}
		if (file.size > 1024 * 1024) {
			imageFailure = 'Image : le fichier dépasse 1 Mio.';
			return;
		}
		const reader = new FileReader();
		reading = true;
		reader.onload = () => {
			const encoded = String(reader.result).split(',')[1];
			image = 'data:' + format + ';base64,' + encoded;
			imageFile = file;
		};
		reader.onerror = () => {
			imageFailure = 'Image : impossible de lire ce fichier.';
		};
		reader.onloadend = () => {
			reading = false;
		};
		reader.readAsDataURL(file);
	}

	function buildRule(): QuizRule {
		switch (kind) {
			case 'choice': {
				const values = options.map((option) => option.trim());
				if (
					values.some((value) => !value) ||
					new Set(values).size !== values.length ||
					!correct.length
				)
					throw new Error(
						'Renseignez des propositions distinctes et cochez au moins une bonne réponse.'
					);
				return { kind, options: values, correct };
			}
			case 'number':
				return { kind, expected, tolerance: tolerance.trim() || '0' };
			case 'text': {
				const values = accepted
					.split('\n')
					.map((value) => value.trim())
					.filter(Boolean);
				if (!values.length || values.length > 16 || values.some((value) => value.length > 300))
					throw new Error(
						'Indiquez de 1 à 16 réponses, une par ligne (300 caractères maximum chacune).'
					);
				return { kind, accepted: values };
			}
		}
	}

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		failure = '';
		try {
			if (competencyIds.length > 50) throw new Error('Sélectionnez au plus 50 compétences.');
			await quizAction(question ? 'edit' : 'create', subject.id, question?.id, {
				title,
				statement,
				prompt,
				image,
				image_alt: image ? imageAlt : '',
				competency_ids: competencyIds,
				rule: buildRule(),
				...(question ? { version: question.version } : {})
			});
			await goto(resolve('/quiz/[subjectId]', subjectParams), {
				invalidateAll: true
			});
		} catch (cause) {
			failure = cause instanceof Error ? cause.message : 'La fiche n’a pas pu être enregistrée.';
		} finally {
			busy = false;
		}
	}
</script>

<div class="box">
	<h1 class="title is-4">{question ? 'Modifier la fiche' : 'Nouvelle fiche'}</h1>
	<div class="tabs is-boxed" aria-label="Vue de la fiche">
		<ul>
			<li class:is-active={tab === 'write'}>
				<button
					class="button is-ghost"
					type="button"
					aria-pressed={tab === 'write'}
					aria-controls={pageId + '-write'}
					onclick={() => (tab = 'write')}>Rédiger</button
				>
			</li>
			<li class:is-active={tab === 'preview'}>
				<button
					class="button is-ghost"
					type="button"
					aria-pressed={tab === 'preview'}
					aria-controls={pageId + '-preview'}
					onclick={() => (tab = 'preview')}>Prévisualisation</button
				>
			</li>
		</ul>
	</div>
	<div id={pageId + '-preview'} hidden={tab !== 'preview'}>
		{#if tab === 'preview'}<QuestionPreview {subject} question={preview} draft />{/if}
	</div>
	<form id={pageId + '-write'} hidden={tab !== 'write'} onsubmit={submit}>
		<fieldset disabled={busy}>
			<div class="field">
				<label class="label" for="quiz-title">Titre</label>
				<input class="input" id="quiz-title" bind:value={title} maxlength="160" required />
			</div>
			<div class="field">
				<label class="label" for="quiz-statement">Énoncé (facultatif)</label>
				<textarea
					class="textarea"
					id="quiz-statement"
					rows="5"
					bind:value={statement}
					maxlength="4000"></textarea>
			</div>
			<div class="field">
				<label class="label" for="quiz-prompt">Question</label>
				<textarea
					class="textarea"
					id="quiz-prompt"
					rows="3"
					bind:value={prompt}
					maxlength="4000"
					required></textarea>
				<p class="help">
					Énoncé ({statement.length}/4000 caractères) · <code>*italique*</code>,
					<code>**gras**</code>, <code>==coloré==</code> · LaTeX dans la question et les
					propositions · <code>$…$</code> intégré, <code>$$…$$</code> sur une ligne.
				</p>
			</div>
			<div class="field">
				<p class="label">Image facultative</p>
				<FileDropzone
					file={imageFile}
					accept="image/png,image/jpeg,.png,.jpg,.jpeg"
					label="Dépôt d’image"
					placeholder={image ? 'Remplacez l’image' : 'Déposez votre image ici'}
					disabled={busy || reading}
					onselect={upload}
				/>
				<p class="help">
					PNG ou JPEG fixe, 1 Mio et 4 mégapixels maximum (par exemple 2 000 × 2 000 px).
				</p>
				{#if imageFailure}<p class="help is-danger" role="alert">{imageFailure}</p>{/if}
				{#if image}
					<label class="label mt-3" for="quiz-image-alt">Description de l’image</label>
					<input class="input" id="quiz-image-alt" bind:value={imageAlt} maxlength="300" required />
					<button
						class="button is-small mt-2"
						type="button"
						disabled={reading}
						onclick={() => {
							image = null;
							imageFile = null;
							imageAlt = '';
						}}>Retirer l’image</button
					>
				{/if}
			</div>
			<div class="field">
				<label class="label" for="quiz-kind">Type de réponse</label>
				<div class="select">
					<select id="quiz-kind" bind:value={kind}>
						<option value="choice">Choix (une ou plusieurs bonnes réponses)</option>
						<option value="number">Nombre ou fraction</option>
						<option value="text">Texte court</option>
					</select>
				</div>
			</div>
			{#if kind === 'choice'}
				<fieldset class="field">
					<legend class="label">Propositions et corrigé</legend>
					{#each options as option, index (index)}
						<div class="mb-2">
							<label class="label is-small" for={'quiz-option-' + index}
								>Proposition {index + 1}</label
							>
							<div class="option">
								<input
									class="input"
									id={'quiz-option-' + index}
									value={option}
									oninput={(event) => (options[index] = event.currentTarget.value)}
									maxlength="300"
									required
								/>
								<label class="checkbox">
									<input
										type="checkbox"
										aria-label={'Bonne réponse pour la proposition ' + (index + 1)}
										bind:group={correct}
										value={index}
									/> Bonne réponse
								</label>
								{#if options.length > 2}
									<button
										class="button is-small"
										aria-label={'Retirer la proposition ' + (index + 1)}
										type="button"
										onclick={() => removeOption(index)}>Retirer</button
									>
								{/if}
							</div>
						</div>
					{/each}
					{#if options.length < 12}
						<button class="button is-small" type="button" onclick={() => options.push('')}
							>Ajouter une proposition</button
						>
					{/if}
				</fieldset>
			{:else if kind === 'number'}
				<div class="field">
					<label class="label" for="quiz-expected">Valeur attendue</label>
					<input
						class="input"
						id="quiz-expected"
						bind:value={expected}
						placeholder="1/2"
						maxlength="80"
						required
					/>
				</div>
				<div class="field">
					<label class="label" for="quiz-tolerance">Tolérance absolue (facultative)</label>
					<input
						class="input"
						id="quiz-tolerance"
						bind:value={tolerance}
						placeholder="0"
						maxlength="80"
					/>
					<p class="help">
						Pour une valeur attendue de 0,5 et une tolérance de 0,01, les réponses de 0,49 à 0,51
						sont acceptées.
					</p>
				</div>
			{:else}
				<div class="field">
					<label class="label" for="quiz-accepted">Réponses acceptées (une par ligne)</label>
					<textarea class="textarea" id="quiz-accepted" bind:value={accepted} required></textarea>
					<p class="help">Les majuscules, les accents et les espaces superflus sont ignorés.</p>
				</div>
			{/if}

			{#if subject.competencies.length}
				<fieldset class="field">
					<legend class="label"
						>Compétences facultatives ({competencyIds.length} sélectionnées)</legend
					>
					{#if subject.competencies.length > 5}
						<label class="label is-small" for="quiz-competency-search"
							>Rechercher une compétence</label
						>
						<input
							class="input mb-2"
							id="quiz-competency-search"
							type="search"
							bind:value={competencyQuery}
							placeholder="Nom ou programme"
						/>
					{/if}
					{#each shownCompetencies as competency (competency.id)}
						<label class="checkbox is-block mb-1">
							<input
								type="checkbox"
								checked={competencyIds.includes(competency.id)}
								onchange={(event) => toggleCompetency(competency.id, event.currentTarget.checked)}
							/>
							{competency.name} <small>({competency.curriculum})</small>
						</label>
					{:else}
						<p class="help">Aucune compétence trouvée.</p>
					{/each}
					{#if matches.length > shownCompetencies.length}
						<p class="help">
							5 sur {matches.length} résultats. Affinez la recherche pour voir les autres.
						</p>
					{/if}
					{#if subject.competencies.length > 5 && competencyIds.length}
						<div class="tags mt-2" aria-label="Compétences sélectionnées">
							{#each subject.competencies.filter( (item) => competencyIds.includes(item.id) ) as item (item.id)}
								<span class="tag"
									>{item.name}<button
										class="delete is-small"
										type="button"
										aria-label={'Retirer ' + item.name}
										onclick={() => toggleCompetency(item.id, false)}
									></button></span
								>
							{/each}
						</div>
					{/if}
				</fieldset>
			{/if}
			{#if failure}<p class="notification is-danger is-light" role="alert">{failure}</p>{/if}
			<div class="buttons">
				<button
					class="button is-primary"
					class:is-loading={busy}
					disabled={busy || reading}
					type="submit"
				>
					Enregistrer
				</button>
				<a
					class="button is-light"
					href={question
						? resolve(`/quiz/[subjectId]?fiche=${question.id}`, subjectParams)
						: resolve('/quiz/[subjectId]', subjectParams)}>Annuler</a
				>
			</div>
		</fieldset>
	</form>
</div>

<style>
	.tabs li.is-active button {
		background: var(--color-soft);
		color: var(--color-ink);
		border-radius: 0.5rem 0.5rem 0 0;
		box-shadow: inset 0 -2px var(--color-primary);
	}
	.option {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex-wrap: wrap;
	}
	.option .input {
		flex: 1 1 14rem;
	}
	.option .checkbox {
		white-space: nowrap;
	}
</style>
