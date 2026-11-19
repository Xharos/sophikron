<script lang="ts">
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import SubjectIdentity from '#lib/components/SubjectIdentity.svelte';
	import type { QuizSummary } from '#lib/quiz';
	import { quizAction } from '../api';
	import QuestionEditor from '../QuestionEditor.svelte';
	import QuestionPreview from '../QuestionPreview.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let filter = $state('all');
	let busy = $state(false);
	let failure = $state('');
	let notice = $state('');
	const subjectParams = $derived({ subjectId: String(data.subject.id) });
	const rows = $derived(
		data.subject.questions.filter(
			(row) => filter === 'all' || row.archived === (filter === 'archived')
		)
	);
	const title = $derived(
		data.view === 'list'
			? data.subject.name
			: data.view === 'preview'
				? data.question.title
				: data.question
					? 'Modifier la fiche'
					: 'Nouvelle fiche'
	);

	async function mutate(row: QuizSummary, command: 'archive' | 'delete'): Promise<void> {
		if (command === 'delete' && !window.confirm(`Supprimer définitivement « ${row.title} » ?`))
			return;
		busy = true;
		failure = '';
		notice = '';
		try {
			const revision = { version: row.version };
			await quizAction(
				command,
				data.subject.id,
				row.id,
				command === 'archive' ? { ...revision, archived: !row.archived } : revision
			);
			await invalidateAll();
			notice =
				command === 'delete'
					? 'Fiche supprimée.'
					: row.archived
						? 'Fiche rendue visible.'
						: 'Fiche archivée.';
		} catch (cause) {
			failure = cause instanceof Error ? cause.message : 'La demande a échoué.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head>
	<title>{title} · Quiz · Sophikron</title>
	<meta name="description" content="Fiches de questions de la matière." />
</svelte:head>

<section class="section">
	<div class="container">
		<nav class="breadcrumb" aria-label="Fil d’Ariane">
			<ul>
				<li><a href={resolve('/quiz')}>Quiz</a></li>
				{#if data.view === 'list'}
					<li class="is-active">
						<a href={resolve('/quiz/[subjectId]', subjectParams)} aria-current="page"
							>{data.subject.name}</a
						>
					</li>
				{:else}
					<li><a href={resolve('/quiz/[subjectId]', subjectParams)}>{data.subject.name}</a></li>
				{/if}
			</ul>
		</nav>

		{#if data.view === 'list'}
			<div
				class="is-flex is-flex-wrap-wrap is-justify-content-space-between is-align-items-center mb-4 heading"
			>
				<h1 class="title is-4 mb-0"><SubjectIdentity subject={data.subject} /></h1>
				{#if data.subject.can_edit}
					<a
						class="button is-primary"
						href={resolve('/quiz/[subjectId]?modifier=nouvelle', subjectParams)}>Nouvelle fiche</a
					>
				{/if}
			</div>

			<div class="field">
				<label class="label" for="quiz-status">Afficher</label>
				<div class="select">
					<select id="quiz-status" bind:value={filter}>
						<option value="all">Toutes les fiches</option>
						<option value="visible">Fiches visibles</option>
						<option value="archived">Fiches archivées</option>
					</select>
				</div>
			</div>
			{#if failure}<p class="notification is-danger is-light" role="alert">{failure}</p>{/if}
			{#if notice}<p class="notification is-success is-light" role="status">{notice}</p>{/if}

			{#if rows.length}
				<div class="table-container">
					<table class="table is-fullwidth is-hoverable">
						<thead>
							<tr
								><th scope="col">Titre</th><th scope="col">Visibilité</th>
								{#if data.subject.can_edit}<th scope="col">Actions</th>{/if}</tr
							>
						</thead>
						<tbody>
							{#each rows as row (row.id)}
								<tr>
									<th scope="row"
										><a
											class="row-link"
											href={resolve(`/quiz/[subjectId]?fiche=${row.id}`, subjectParams)}
											>{row.title}</a
										></th
									>
									<td>
										{#if data.subject.can_edit}
											<button
												class={row.archived
													? 'button is-small'
													: 'button is-small is-success is-light'}
												type="button"
												role="switch"
												aria-checked={!row.archived}
												aria-label={`Visibilité de ${row.title}`}
												disabled={busy}
												onclick={() => mutate(row, 'archive')}
											>
												{row.archived ? 'Archivée' : 'Visible'}
											</button>
										{:else}
											<span class="tag">{row.archived ? 'Archivée' : 'Visible'}</span>
										{/if}
									</td>
									{#if data.subject.can_edit}
										<td>
											<div class="buttons">
												<a
													class="button is-small"
													href={resolve(`/quiz/[subjectId]?modifier=${row.id}`, subjectParams)}
													aria-label={`Modifier ${row.title}`}>Modifier</a
												>
												<button
													class="button is-small is-danger is-light"
													type="button"
													aria-label={`Supprimer ${row.title}`}
													disabled={busy}
													onclick={() => mutate(row, 'delete')}>Supprimer</button
												>
											</div>
										</td>
									{/if}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<p>
					{filter === 'all' ? 'Aucune fiche dans cette matière.' : 'Aucune fiche pour ce statut.'}
				</p>
			{/if}
		{:else if data.view === 'edit'}
			{#key `${data.subject.id}:${data.question?.id}:${data.question?.version}`}
				<QuestionEditor subject={data.subject} question={data.question} />
			{/key}
		{:else}
			{#key `${data.subject.id}:${data.question.id}:${data.question.version}`}
				<QuestionPreview subject={data.subject} question={data.question} />
			{/key}
		{/if}
	</div>
</section>

<style>
	.heading {
		gap: 1rem;
	}
	tr {
		position: relative;
	}
	.row-link::after {
		content: '';
		position: absolute;
		inset: 0;
	}
	td .button {
		position: relative;
		z-index: 1;
	}
	th,
	td {
		vertical-align: middle;
	}
</style>
