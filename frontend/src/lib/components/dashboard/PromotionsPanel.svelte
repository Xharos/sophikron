<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { command, read } from '#lib/dashboard';
	import type { Page, Promotion } from '#lib/types';
	import Icon from '../Icon.svelte';
	import Pagination from '../Pagination.svelte';
	import AccountsPanel from './AccountsPanel.svelte';
	import PromotionEditor from './PromotionEditor.svelte';
	import MembershipPicker from './MembershipPicker.svelte';
	let {
		administrator,
		currentUserId,
		initialPromotion,
		initialEdit = false
	}: {
		administrator: boolean;
		currentUserId: number;
		initialPromotion?: Promotion;
		initialEdit?: boolean;
	} = $props();
	let query = $state('');
	let filterState = $state('true');
	let offset = $state(0);
	let total = $state(0);
	let items = $state<Promotion[]>([]);
	let selected = $state<Promotion | null>(untrack(() => initialPromotion ?? null));
	let editor = $state<Promotion | 'new' | null>(
		untrack(() => (initialEdit ? (initialPromotion ?? null) : null))
	);
	let adding = $state(false);
	let confirmArchive = $state(false);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let ready = $state(false);
	let revision = $state(0);
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const q = query;
		const filter = filterState;
		const page = offset;
		void revision;
		if (!ready) return;
		const controller = new AbortController();
		const timer = setTimeout(
			async () => {
				loading = true;
				message = '';
				try {
					const result = await read<Page<Promotion>>(
						'promotions',
						{ q, is_active: filter || undefined, offset: page, limit: 12 },
						controller.signal
					);
					items = result.items;
					total = result.total;
					if (selected)
						selected = result.items.find((item) => item.id === selected?.id) ?? selected;
				} catch (cause) {
					if (!controller.signal.aborted) message = (cause as Error).message;
				} finally {
					if (!controller.signal.aborted) loading = false;
				}
			},
			q ? 220 : 0
		);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	});
	async function archive(): Promise<void> {
		if (!selected) return;
		busy = true;
		message = '';
		try {
			selected = await command<Promotion>('updatePromotion', {
				id: selected.id,
				data: { is_active: !selected.is_active }
			});
			confirmArchive = false;
			revision += 1;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	function changed(): void {
		revision += 1;
	}
</script>

<section class="workspace-panel">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Promotions</p>
			<h2 class="title is-4 mb-2">
				{administrator ? 'Vos groupes, au même endroit.' : 'Mes promotions'}
			</h2>
			<p class="muted text-small">
				{administrator
					? 'Créez, organisez et retrouvez vos promotions.'
					: 'Retrouvez les élèves de vos promotions, y compris les comptes archivés.'}
			</p>
		</div>
		{#if administrator}<button class="button is-primary" onclick={() => (editor = 'new')}
				><Icon name="plus" />Nouvelle promotion</button
			>{/if}
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if selected}
		<button
			class="button is-text mb-4"
			onclick={() => {
				selected = null;
				confirmArchive = false;
			}}><Icon name="previous" />Toutes les promotions</button
		>
		<div class="promotion-detail" style={`--promotion-color: ${selected.color}`}>
			<div>
				<span class="eyebrow"
					>{selected.year} · {selected.is_active ? 'Promotion active' : 'Promotion archivée'}</span
				>
				<h3 class="title is-3">{selected.identifier}</h3>
				<p class="muted">
					{selected.student_count ?? 0} élève(s){#if administrator}
						· {selected.member_count ?? 0} membre(s) au total{/if}
				</p>
			</div>
			{#if administrator}<div class="profile-buttons">
					<button class="button is-light" onclick={() => (editor = selected)}
						><Icon name="edit" />Modifier</button
					>
					<button class="button is-light" onclick={() => (confirmArchive = !confirmArchive)}
						><Icon name={selected.is_active ? 'archive' : 'restore'} />{selected.is_active
							? 'Archiver'
							: 'Réactiver'}</button
					>
					<button
						class="button is-primary"
						disabled={!selected.is_active}
						onclick={() => (adding = true)}><Icon name="plus" />Ajouter des membres</button
					>
				</div>{/if}
		</div>
		{#if confirmArchive}<div class="confirmation-panel mt-4">
				<p>
					{selected.is_active
						? 'Archiver cette promotion ? Ses membres seront conservés.'
						: 'Réactiver cette promotion ? Vous pourrez à nouveau y ajouter des membres.'}
				</p>
				<div class="buttons mt-3">
					<button
						class="button is-primary"
						disabled={busy}
						class:is-loading={busy}
						onclick={archive}>Confirmer</button
					><button class="button is-light" disabled={busy} onclick={() => (confirmArchive = false)}
						>Annuler</button
					>
				</div>
			</div>{/if}
	{:else}
		<div class="list-toolbar">
			<div class="search-field">
				<Icon name="search" /><input
					class="input"
					aria-label="Rechercher une promotion"
					placeholder="Rechercher une promotion…"
					bind:value={query}
					oninput={() => (offset = 0)}
				/>
			</div>
			<div class="select">
				<select
					aria-label="État des promotions"
					bind:value={filterState}
					onchange={() => (offset = 0)}
					><option value="true">Actives</option><option value="false">Archivées</option><option
						value="">Toutes les promotions</option
					></select
				>
			</div>
		</div>
		{#if loading}<p class="loading-state" role="status">
				Chargement des promotions…
			</p>{:else if items.length === 0}<div class="empty-state">
				<Icon name="promotions" size={30} />
				<p>Aucune promotion à afficher.</p>
			</div>
		{:else}<div class="promotion-grid">
				{#each items as promotion (promotion.id)}<button
						class="promotion-card"
						style={`--promotion-color: ${promotion.color}`}
						onclick={() => (selected = promotion)}
					>
						<span class="promotion-card-top"
							><span class="promotion-year">{promotion.year}</span><Icon
								name="open"
								size={14}
							/></span
						>
						<strong>{promotion.identifier}</strong><span class="muted text-small"
							>{promotion.student_count ?? 0} élève(s) · {promotion.is_active
								? 'Active'
								: 'Archivée'}</span
						></button
					>{/each}
			</div>{/if}
		<Pagination {offset} limit={12} {total} busy={loading} onchange={(value) => (offset = value)} />
	{/if}
</section>
{#if selected}{#key selected.id}<AccountsPanel
			{administrator}
			{currentUserId}
			promotionId={selected.id}
			onchanged={changed}
		/>{/key}{/if}
{#if editor}<PromotionEditor
		promotion={editor === 'new' ? undefined : editor}
		onclose={() => (editor = null)}
		onsaved={(promotion) => {
			if (selected?.id === promotion.id) selected = promotion;
			changed();
		}}
	/>{/if}
{#if adding && selected}<MembershipPicker
		promotion={selected}
		onclose={() => (adding = false)}
		onsaved={changed}
	/>{/if}
