<script lang="ts">
	import {
		lessonCommand,
		periodLabel,
		type ElementKind,
		type LessonDetail,
		type LessonElement
	} from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import ResourceBody from './ResourceBody.svelte';
	let {
		table,
		lesson,
		editing,
		busy,
		onedit,
		onadd,
		onremove,
		onupdate
	}: {
		table: LessonElement;
		lesson: LessonDetail;
		editing: boolean;
		busy: boolean;
		onedit: (item: LessonElement) => void;
		onadd: (kind: ElementKind, parent: LessonElement, row: number, column: number) => void;
		onremove: (item: LessonElement) => void;
		onupdate: (lesson: LessonDetail) => void;
	} = $props();
	let saving = $state(false);
	let message = $state('');
	let newColumn = $state('');
	const disabled = $derived(busy || saving);
	function cell(row: number, column: number): LessonElement | undefined {
		return lesson.elements.find(
			(item) =>
				item.parent_id === table.id && item.row_index === row && item.column_index === column
		);
	}
	async function change(action: string, index = 0, label = ''): Promise<void> {
		if (
			action.startsWith('remove') &&
			!window.confirm('Supprimer cette ligne ou colonne et les documents qu’elle contient ?')
		)
			return;
		saving = true;
		message = '';
		try {
			onupdate(
				await lessonCommand<LessonDetail>('changeTable', {
					lessonId: lesson.id,
					elementId: table.id,
					data: { expected_version: lesson.version, action, index, label }
				})
			);
			newColumn = '';
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			saving = false;
		}
	}
</script>

{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
<!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard focus enables horizontal scrolling.) -->
<div
	class="table-container table-scroll"
	role="region"
	aria-label={table.title || 'Tableau de ressources'}
	tabindex="0"
>
	<table
		class="table is-bordered is-striped is-fullwidth resource-table"
		class:editing
		style:min-width={`${table.table_columns.length * (editing ? 15 : 12) + (editing ? 12 : 0)}rem`}
	>
		<caption class="is-sr-only">{table.title}</caption>
		<thead
			><tr
				>{#each table.table_columns as label, column (column)}<th scope="col">
						{#if editing}<label class="is-sr-only" for={`column-${table.id}-${column}`}
								>Titre de la colonne {column + 1}</label
							><input
								class="input is-small"
								id={`column-${table.id}-${column}`}
								value={label}
								maxlength="100"
								{disabled}
								onchange={(event) => {
									const value = event.currentTarget.value.trim();
									if (value && value !== label) void change('rename_column', column, value);
								}}
							/><button
								class="button is-small is-light mt-2"
								disabled={disabled || table.table_columns.length <= 1}
								onclick={() => change('remove_column', column)}
								>Supprimer la colonne {column + 1}</button
							>{:else}{label}{/if}
					</th>{/each}{#if editing}<th scope="col"
						><span class="is-sr-only">Actions de ligne</span></th
					>{/if}</tr
			></thead
		>
		<tbody
			>{#each Array.from({ length: table.table_rows }, (_, row) => row) as row (row)}<tr>
					{#each table.table_columns as label, column (column)}{@const item = cell(row, column)}<td
							data-column={label}
						>
							{#if item}
								{#if item.title && item.kind !== 'file' && item.kind !== 'youtube'}<h4
										class="title is-6"
									>
										{item.title}
									</h4>{/if}
								{#if lesson.staff_view && (item.effective_starts_on || item.effective_ends_on)}<p
										class="help mb-2"
									>
										{periodLabel(
											item.effective_starts_on,
											item.effective_ends_on
										)}{item.effective_audience === 'staff' ? ' · Professeurs uniquement' : ''}
									</p>{/if}
								<ResourceBody
									{item}
									lessonId={lesson.id}
									color={lesson.color}
									staffView={lesson.staff_view}
								/>
								{#if editing}<div class="cell-actions">
										<button class="button is-small is-light" {disabled} onclick={() => onedit(item)}
											><Icon name="edit" size={13} />Modifier</button
										><button
											class="button is-small is-light"
											{disabled}
											onclick={() => onremove(item)}>Vider la cellule</button
										>
									</div>{/if}
							{:else if editing}<div class="cell-empty">
									<span class="muted text-small">Cellule vide · ligne {row + 1}</span><button
										class="button is-small is-light"
										{disabled}
										onclick={() => onadd('file', table, row, column)}>Document</button
									><button
										class="button is-small is-light"
										{disabled}
										onclick={() => onadd('text', table, row, column)}>Texte</button
									><button
										class="button is-small is-light"
										{disabled}
										onclick={() => onadd('youtube', table, row, column)}>YouTube</button
									>
								</div>{:else}<span aria-label="Cellule vide">—</span>{/if}
						</td>{/each}
					{#if editing}<td class="row-action"
							><button
								class="button is-small is-light"
								disabled={disabled || table.table_rows <= 1}
								onclick={() => change('remove_row', row)}>Supprimer la ligne {row + 1}</button
							></td
						>{/if}
				</tr>{/each}</tbody
		>
	</table>
</div>
{#if editing}<div class="table-actions">
		<button
			class="button is-light is-small"
			disabled={disabled || table.table_rows >= 20}
			onclick={() => change('add_row')}><Icon name="plus" size={13} />Ajouter une ligne</button
		>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void change('add_column', 0, newColumn);
			}}
		>
			<label class="is-sr-only" for={`new-column-${table.id}`}>Titre de la nouvelle colonne</label
			><input
				id={`new-column-${table.id}`}
				class="input is-small"
				placeholder="Titre de la nouvelle colonne"
				bind:value={newColumn}
				maxlength="100"
				required
				{disabled}
			/><button
				class="button is-light is-small"
				disabled={disabled || table.table_columns.length >= 6}>Ajouter une colonne</button
			>
		</form>
	</div>
{/if}

<style>
	.table-scroll {
		overflow-x: auto;
		max-width: 100%;
		border-radius: 0.6rem;
		border: var(--border-thin);
		overscroll-behavior-x: contain;
	}
	.table-scroll:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
	}
	.resource-table {
		table-layout: fixed;
		margin-bottom: 0;
		--bulma-table-head-background-color: var(--color-soft);
		--bulma-table-head-cell-color: var(--color-ink);
	}
	.resource-table td,
	.resource-table th {
		overflow-wrap: anywhere;
		vertical-align: top;
		padding: 0.8rem;
	}
	.cell-actions,
	.cell-empty,
	.table-actions,
	.table-actions form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
	}
	.cell-actions {
		margin-top: 0.8rem;
	}
	.cell-empty > span {
		width: 100%;
	}
	.table-actions {
		margin-top: 0.8rem;
	}
	.table-actions input {
		width: 230px;
		max-width: 100%;
	}
	.table-actions form {
		min-width: 0;
		max-width: 100%;
	}
</style>
