"""Deterministic evidence plots with complete source rows and public selection rules."""
import numpy as np
import pandas as pd
from .generic_workflow import json_write
from .contrast_quantification import ContrastEstimator
from .study_design import same_time


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
        ax.set_title(name.replace('_',' '));fig.tight_layout()
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
    def curves(ax,f,entity,value,track=None):
        if track is not None:f=f.loc[f.track.eq(track)]
        keys=[entity,'arm_id','reference_condition_id']
        for key,g in list(f.groupby(keys,sort=True))[:12]:
            g=g.sort_values(['time_min','contrast_id']);ax.plot(g.time_min,g[value],marker='o',markersize=3,label='/'.join(map(str,key)))
        ax.set_xlabel('Actual target time (minutes)');ax.set_ylabel('Log2 contrast, recorded reference')
        if len(f):ax.legend(fontsize=5)
        else:empty(ax)
    save('kinase_footprints','kinase/kinase_temporal_profiles',lambda ax,f:curves(ax,f,'candidate_id','activity_magnitude','curated_A'),'first 12 stable candidate/arm/reference series; curated track; gaps remain gaps')
    save('protein_trajectories','quant/protein_contrasts',lambda ax,f:curves(ax,f,'protein_group','log2_change'),'first 12 stable protein/arm/reference series; all proteins in source')
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
