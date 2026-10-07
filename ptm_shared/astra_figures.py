"""Deterministic evidence plots with complete source rows and public selection rules."""
import json
import numpy as np
import pandas as pd
from .generic_workflow import json_write
from .contrast_quantification import ContrastEstimator
from .study_design import same_time
from .feature_identity import project_reader_display_identity


CURVE_SELECTION_POLICY='finite_observation_count_desc_stable_series_id_12.v1'


def curve_series(frame,entity,value,design,track=None,candidate_edges=None):
    """Select display series only; keep every original row of selected series.

    Finite values at finite times qualify, regardless of coverage thresholds.
    Missing points stay in the plotting arrays so lines cannot bridge gaps.
    The selection ledger covers every series in the requested track, including
    exclusions. Plot keys are presentation crosswalks, not new scientific IDs.
    """
    f=frame.loc[frame.track.eq(track)].copy() if track is not None else frame.copy()
    keys=[entity,'arm_id','reference_condition_id','pairing']
    columns=keys+['plot_series_key','display_label','candidate_taxa','candidate_accessions','candidate_resolution',
                  'finite_observation_count','finite_timepoint_count','source_row_count','missing_value_count',
                  'coverage_adequate_observations','selected','selection_rank','selection_reason','selection_policy']
    if f.empty:return pd.DataFrame(columns=columns),f.assign(plot_series_key=pd.Series(dtype=str),display_label=pd.Series(dtype=str),plotted_point=pd.Series(dtype=bool))
    if f[[entity,'arm_id','reference_condition_id','contrast_id']].isna().any().any():
        raise ValueError('Curve entity/series/contrast IDs must be present')
    if f.duplicated([entity,'contrast_id']).any():raise ValueError('Duplicate curve entity/contrast observations')
    estimator=ContrastEstimator(design)
    metadata={c['contrast_id']:estimator.metadata(c) for c in design['contrasts']}
    for r in f[['contrast_id','arm_id','reference_condition_id','time_min']+(['pairing'] if 'pairing' in f else [])].drop_duplicates().to_dict('records'):
        if r['contrast_id'] not in metadata:raise ValueError(f'Unknown curve contrast: {r["contrast_id"]}')
        expected=metadata[r['contrast_id']]
        for field in ['arm_id','reference_condition_id','pairing','time_min']:
            if field not in r or pd.isna(r[field]):continue
            agrees=same_time(r[field],expected[field]) if field=='time_min' else r[field]==expected[field]
            if not agrees:raise ValueError(f'Conflicting curve {field}: {r["contrast_id"]}')
    if 'pairing' not in f:f['pairing']=f.contrast_id.map(lambda cid:metadata[cid]['pairing'])
    if f.pairing.isna().any():raise ValueError('Curve pairing metadata must be explicit')
    def text_values(series):
        return ';'.join(sorted({f'{v:g}' if isinstance(v,(int,float)) else str(v) for v in series.dropna() if str(v).strip()}))
    identities={}
    if candidate_edges is not None and not candidate_edges.empty:
        fields=[c for c in ['candidate_gene','candidate_accession','candidate_resolution','kinase_taxon'] if c in candidate_edges]
        identities={cid:{c:text_values(g[c]) for c in fields}
                    for cid,g in candidate_edges[['candidate_id']+fields].drop_duplicates().groupby('candidate_id',sort=True)}
    groups=list(f.groupby(keys,sort=True,dropna=False));rows=[];points={}
    for key,g in groups:
        g=g.sort_values(['time_min','contrast_id'],na_position='last').copy()
        valid=np.isfinite(g[value].to_numpy(float)) & np.isfinite(g.time_min.to_numpy(float))
        identity=dict(identities.get(key[0],{}))
        label_field='candidate_gene' if entity=='candidate_id' else 'gene'
        if label_field in g:identity[label_field]=text_values(g[label_field]) or identity.get(label_field,'')
        identity['protein_group']=key[0] if entity=='protein_group' else ''
        unit='kinase_candidate' if entity=='candidate_id' else 'protein_group_abundance'
        plot_key=json.dumps([entity,*key,track],separators=(',',':'))
        row={**dict(zip(keys,key)),'plot_series_key':plot_key,
             'display_label':project_reader_display_identity(identity,reader_measurement_unit=unit),
             'candidate_taxa':identity.get('kinase_taxon',''),'candidate_accessions':identity.get('candidate_accession',''),
             'candidate_resolution':identity.get('candidate_resolution',''),
             'finite_observation_count':int(valid.sum()),'finite_timepoint_count':int(g.loc[valid,'time_min'].nunique()),
             'source_row_count':len(g),'missing_value_count':int(g[value].isna().sum()),
             'coverage_adequate_observations':int((g.coverage_adequate.eq(True) & valid).sum()) if 'coverage_adequate' in g else None}
        rows.append(row);points[plot_key]=g
    selection=pd.DataFrame(rows).sort_values(['finite_observation_count']+keys,ascending=[False]+[True]*len(keys)).reset_index(drop=True)
    selection['selected']=selection.finite_observation_count.gt(0) & (selection.index<12)
    selection['selection_rank']=pd.Series(range(1,len(selection)+1),dtype='Int64').where(selection.finite_observation_count.gt(0))
    selection['selection_reason']=np.where(selection.selected,'selected_finite_observation_rank',
                                         np.where(selection.finite_observation_count.gt(0),'display_limit_12','no_finite_value_at_finite_time'))
    selection['selection_policy']=CURVE_SELECTION_POLICY
    # Taxonomy comes only from recorded enzyme metadata, never substrate/host.
    # Same-name entities remain separate even when taxonomy is missing or equal.
    for _,indices in selection.groupby('display_label',sort=True).groups.items():
        group=selection.loc[indices]
        if group[entity].nunique()>1:
            for i in indices:
                taxon=selection.at[i,'candidate_taxa']
                if taxon:selection.at[i,'display_label']+=f' [taxon {taxon}]'
    for _,indices in selection.groupby('display_label',sort=True).groups.items():
        ids=sorted(selection.loc[indices,entity].unique())
        if len(ids)>1:
            for i in indices:selection.at[i,'display_label']+=f' (entity {ids.index(selection.at[i,entity])+1})'
    arms={a['arm_id']:a['name'] for a in design['arms']}
    if len(selection[['arm_id','reference_condition_id','pairing']].drop_duplicates())>1:
        for i,r in selection.iterrows():
            ref=estimator.conditions[r.reference_condition_id]
            selection.at[i,'display_label']+=f' / {arms[r.arm_id]} vs {ref["label"]} / {r.pairing}'
        # Identical human labels must not hide distinct arm/reference IDs.
        for _,indices in selection.groupby('display_label',sort=True).groups.items():
            if len(indices)>1:
                for n,i in enumerate(sorted(indices,key=lambda i:selection.at[i,'plot_series_key']),1):
                    selection.at[i,'display_label']+=f' (series {n})'
    selected=[]
    for r in selection.loc[selection.selected].itertuples():
        g=points[r.plot_series_key].assign(plot_series_key=r.plot_series_key,display_label=r.display_label)
        g['plotted_point']=np.isfinite(g[value].to_numpy(float)) & np.isfinite(g.time_min.to_numpy(float))
        selected.append(g)
    return selection,pd.concat(selected,ignore_index=True) if selected else f.iloc[:0].assign(
        plot_series_key=pd.Series(dtype=str),display_label=pd.Series(dtype=str),plotted_point=pd.Series(dtype=bool))


def heatmap_grid(frame,index,column,value,design):
    """Keep cell identity/NA; order only observed columns by canonical minutes.

    Contrast series retain arm, declared reference and pairing. Detection counts
    retain distinct condition IDs, including controls actually present in rows.
    No quantification or time-label parsing is run here.
    """
    if frame[[index,column]].isna().any().any():
        raise ValueError('Heatmap entity/column IDs must be present')
    duplicates=frame.loc[frame.duplicated([index,column],keep=False),[index,column]]
    if len(duplicates):
        raise ValueError(f'Duplicate heatmap cells ({index}, {column}): {duplicates.head(5).to_dict("records")}')
    estimator=ContrastEstimator(design)
    conditions=estimator.conditions
    contrasts={r['contrast_id']:r for r in design['contrasts']}
    arms={r['arm_id']:r['name'] for r in design['arms']}
    def condition_label(cid):
        c=conditions[cid];time=float(c['time']['minutes']);label=c['label']
        clock=f'{time:g} min'
        return clock if label.replace(' ','').lower()==clock.replace(' ','') else f'{label} ({clock})'
    records=[]
    for cid in frame[column].unique():
        if column=='contrast_id':
            if cid not in contrasts:raise ValueError(f'Unknown heatmap contrast: {cid}')
            r=estimator.metadata(contrasts[cid])
        elif column=='condition_id':
            if cid not in conditions:raise ValueError(f'Unknown heatmap condition: {cid}')
            c=conditions[cid]
            r={'condition_id':cid,'arm_id':c['arm_id'],'time_min':(c.get('time') or {}).get('minutes'),
               'reference_condition_id':None,'pairing':None}
        else:raise ValueError(f'Unsupported heatmap column: {column}')
        if r['time_min'] is None or not np.isfinite(float(r['time_min'])):
            raise ValueError(f'Canonical heatmap time unavailable: {cid}')
        r['time_min']=float(r['time_min'])
        r.update(column_id=cid,arm_label=arms[r['arm_id']],condition_label=conditions[r['condition_id']]['label'])
        records.append(r)
    metadata=pd.DataFrame(records).set_index('column_id',drop=False)
    metadata.index.name=None
    # Validate supplied numeric times and identity metadata against the design;
    # never silently overwrite contradictory table metadata for presentation.
    fields=[k for k in ('time_min','arm_id','condition_id','target_condition_id','reference_condition_id','pairing')
            if k in frame and k!=column and (column=='contrast_id' or k in ('time_min','arm_id'))]
    for row in frame[[column]+fields].drop_duplicates().to_dict('records'):
        expected=metadata.loc[row[column]]
        for key in fields:
            if pd.isna(row[key]):continue
            agrees=same_time(row[key],expected[key]) if key=='time_min' else row[key]==expected[key]
            if not agrees:raise ValueError(f'Conflicting heatmap {key}: {row[column]}')
    if column=='contrast_id':
        order=metadata.sort_values(['arm_label','arm_id','reference_time_min','reference_label','reference_condition_id','pairing','time_min','column_id'])
        multiple=len(metadata[['arm_id','reference_condition_id','pairing']].drop_duplicates())>1
        labels=[condition_label(r.condition_id)+(f'\n{r.arm_label} / vs {condition_label(r.reference_condition_id)}\n{r.pairing}' if multiple else '')
                for r in order.itertuples()]
    else:
        order=metadata.sort_values(['time_min','arm_label','condition_label','column_id'])
        # A single treatment with its control needs no repetitive arm prefix.
        series={(conditions[c['target_condition_id']]['arm_id'],c['reference_condition_id'],c.get('pairing'))
                for c in design['contrasts'] if c['target_condition_id'] in metadata.index}
        labels=[condition_label(r.condition_id)+(f'\n{r.arm_label}' if len(series)>1 else '') for r in order.itertuples()]
    duplicates=pd.Series(labels).duplicated(keep=False)
    labels=[label+(f'\n(column {i+1})' if duplicates.iloc[i] else '') for i,label in enumerate(labels)]
    order=order.copy();order['display_label']=labels;order['column_order']=range(len(order))
    # Keep the existing first-50 stable-row policy. pivot refuses aggregation.
    grid=frame.pivot(index=index,columns=column,values=value).sort_index().iloc[:50]
    return grid.reindex(columns=order.column_id.tolist()),order.reset_index(drop=True)


def figure_packet(tables,directory,design):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt']='PTM-Astra-v4'
    output=directory/'figures';output.mkdir(exist_ok=True);legends=[]
    def save(name,key,draw,selection):
        frame=tables[key];frame.to_csv(output/(name+'_source.csv'),index=False)
        fig,ax=plt.subplots(figsize=(10,5));details=draw(ax,frame) or {}
        ax.set_title(details.get('display_title',name.replace('_',' ')));fig.tight_layout()
        fig.savefig(output/(name+'.svg'),metadata={'Date':None});plt.close(fig)
        legends.append({'figure_id':name,'source_table':key,'source_data':name+'_source.csv','selection':selection,
                        'missing':'omitted points or gray cells, never numeric zero','error_bars':'none; technical variation is not a biological CI','full_source_rows':len(frame),**details})
    def empty(ax):ax.text(.5,.5,'Not evaluable: see readiness and source data',ha='center',transform=ax.transAxes)
    def bars(ax,f):
        ax.barh(f.metric,f['count']);ax.set_xlabel('Count (row grain and denominator in source data)')
    save('coverage','evidence/coverage_funnel',bars,'all recorded coverage metrics')
    def qc(ax,f):
        groups=[(str(k),g.log2_SD.dropna().to_numpy()) for k,g in f.groupby('track',sort=True)]
        groups=[(k,v) for k,v in groups if len(v)]
        if groups:
            ax.boxplot([v for _,v in groups],showfliers=False)
            ax.set_xticks(range(1,len(groups)+1),[k for k,_ in groups])
        else:empty(ax)
        ax.set_ylabel('Within-condition log2 SD (measurement dispersion)')
    save('technical_dispersion','evidence/technical_dispersion',qc,'all finite rows; boxes show distribution of technical dispersion, not confidence intervals')
    def correction(ax,f):
        for name,g in f.loc[f.included].groupby('classification',sort=True):
            ax.scatter(g.U_joint,g.A,s=8,alpha=.5,label=name)
        limits=ax.get_xlim();ax.plot(limits,limits,color='black',linestyle='--',linewidth=.6)
        ax.set_xlabel('U_joint (log2 PTM contrast)');ax.set_ylabel('A (log2 parent-adjusted contrast)')
        if len(f):ax.legend(fontsize=6)
    save('parent_correction','evidence/parent_adjustment_impact',correction,'all eligible comparisons; categories are operational effects, not kinase activation')
    def upa(ax,f):
        f=f.loc[f.included].assign(size=lambda x:x.P_joint.abs()).sort_values(['size','form_id','contrast_id'],ascending=[False,True,True]).head(12)
        if len(f):
            x=np.arange(len(f))
            for i,(key,color) in enumerate([('U_joint','#4677af'),('P_joint','#a28a47'),('A','#a54848')]):ax.bar(x+(i-1)*.25,f[key],width=.25,label=key,color=color)
            ax.set_xticks(x,[a+'/'+b for a,b in zip(f.form_id,f.contrast_id)],rotation=50,ha='right',fontsize=6);ax.legend()
        else:empty(ax)
        ax.set_ylabel('Log2 contrast, identical joint masks')
    save('U_P_A_examples','evidence/parent_adjustment_impact',upa,'12 largest absolute P_joint, ties form/contrast ID; all opposing rows retained in source')
    def curves(ax,f,entity,value,name,track=None):
        selection,points=curve_series(f,entity,value,design,track,tables.get('kinase/kinase_candidate_edges'))
        selection.to_csv(output/(name+'_selection.csv'),index=False)
        points.to_csv(output/(name+'_points.csv'),index=False)
        ax.figure.set_size_inches(12,5)
        for n,r in enumerate(selection.loc[selection.selected].itertuples(),1):
            g=points.loc[points.plot_series_key.eq(r.plot_series_key)]
            # Pass all timepoints, including NA, to matplotlib. A singleton is
            # a marker; nonfinite entries break the path instead of bridging it.
            line,=ax.plot(g.time_min.to_numpy(float),g[value].to_numpy(float),marker='o',markersize=4,
                         label=f'{r.display_label} (n={r.finite_observation_count})')
            line.set_gid(f'curve-series-{n}')
        ax.set_xlabel('Actual target time (minutes), recorded reference')
        ax.set_ylabel('Substrate footprint (log2, parent-adjusted)' if track else 'Protein abundance contrast (log2)')
        if selection.selected.any():ax.legend(fontsize=8,loc='upper left',bbox_to_anchor=(1.01,1),title='Finite observations (n)',title_fontsize=8)
        else:ax.text(.5,.5,'Not evaluable: no finite observations\nat recorded times'+(f' in {track}' if track else ''),
                     ha='center',va='center',transform=ax.transAxes)
        return {'selection_metadata':name+'_selection.csv','plotted_data':name+'_points.csv','selection_policy':CURVE_SELECTION_POLICY,
                'series_grain':[entity,'arm_id','reference_condition_id','pairing','track'] if track else [entity,'arm_id','reference_condition_id','pairing'],
                'selected_series':int(selection.selected.sum()),'plotted_points':int(selection.loc[selection.selected,'finite_observation_count'].sum()),
                'coverage_policy':'no_coverage_threshold_for_display; recorded coverage retained in points',
                'display_title':f'Kinase substrate footprints ({track}; exploratory)' if track else 'Protein abundance trajectories'}
    save('kinase_footprints','kinase/kinase_temporal_profiles',lambda ax,f:curves(ax,f,'candidate_id','activity_magnitude','kinase_footprints','curated_A'),
         'up to 12 series with finite observations, count descending then stable entity/arm/reference/pairing IDs; curated_A descriptive footprint, not a kinase activity test')
    save('protein_trajectories','quant/protein_contrasts',lambda ax,f:curves(ax,f,'protein_group','log2_change','protein_trajectories'),
         'up to 12 series with finite observations, count descending then stable entity/arm/reference/pairing IDs; all proteins in source')
    def heat(ax,f,index,column,value,name):
        if f.empty:return empty(ax)
        grid,metadata=heatmap_grid(f,index,column,value,design)
        if grid.empty:return empty(ax)
        metadata.to_csv(output/(name+'_columns.csv'),index=False)
        ax.figure.set_size_inches(max(10,len(grid.columns)*1.1),5)
        cmap=plt.get_cmap('coolwarm').with_extremes(bad='#bdbdbd')
        image=ax.imshow(np.ma.masked_invalid(grid.to_numpy(float)),aspect='auto',cmap=cmap)
        ax.set_xticks(range(len(grid.columns)),metadata.display_label,rotation=45,ha='right',fontsize=8)
        for i,label in enumerate(ax.get_xticklabels()):label.set_gid(f'heatmap-column-{i}')
        ax.set_yticks(range(len(grid)),list(map(str,grid.index)),fontsize=5);ax.figure.colorbar(image,ax=ax)
        if column=='contrast_id' and len(metadata[['arm_id','reference_condition_id','pairing']].drop_duplicates())==1:
            r=metadata.iloc[0]
            reference=next(c for c in design['conditions'] if c['condition_id']==r.reference_condition_id)
            ax.set_xlabel(f'{r.arm_label} / reference: {reference["label"]} ({r.reference_time_min:g} min) / pairing: {r.pairing}')
        else:ax.set_xlabel('Distinct conditions / actual time (minutes)')
        return {'column_metadata':name+'_columns.csv','column_order_policy':'canonical_numeric_minutes_with_distinct_arm_reference_pairing.v1',
                'duplicate_cell_policy':'error_no_aggregation'}
    save('substrate_contrast_heatmap','quant/comparisons',lambda ax,f:heat(ax,f,'form_id','contrast_id','A','substrate_contrast_heatmap'),'first 50 stable form IDs, every explicit contrast; NA gray')
    save('emerging_detection','evidence/emergence_evidence',lambda ax,f:heat(ax,f,'form_id','condition_id','detected_n','emerging_detection'),'first 50 stable forms, actual condition detection counts; shared observations not independent replicates')
    def timing(ax,f):
        f=f.dropna(subset=['source_peak_min','target_peak_min'])
        if len(f):ax.scatter(f.source_peak_min,f.target_peak_min,s=12,alpha=.35)
        else:empty(ax)
        ax.set_xlabel('Source observed peak time (minutes)');ax.set_ylabel('Target observed peak time (minutes)')
    save('cross_layer_timing','temporal/cross_layer_links',timing,'all finite supported cross-layer links; sampled peaks are not causal lag estimates')
    json_write(output/'figure_legends.json',legends)
