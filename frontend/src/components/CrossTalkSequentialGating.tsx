import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface GatingEvent {
  gene: string;
  leading_ptm: string;
  lagging_ptm: string;
  time_lag_minutes: number;
  leading_first_tp: string;
  lagging_first_tp: string;
  mechanism_hint: string;
}

interface CrossTalkSequentialGatingProps {
  gatingEvents: GatingEvent[];
  primaryPtmType: string;
  secondaryPtmType: string;
}

export default function CrossTalkSequentialGating({
  gatingEvents,
  primaryPtmType,
  secondaryPtmType,
}: CrossTalkSequentialGatingProps) {
  const [selectedEvent, setSelectedEvent] = useState<GatingEvent | null>(null);

  const pType = primaryPtmType?.charAt(0).toUpperCase() + primaryPtmType?.slice(1) || 'Primary';
  const sType = secondaryPtmType?.charAt(0).toUpperCase() + secondaryPtmType?.slice(1) || 'Secondary';

  // Sort by time lag
  const sortedEvents = useMemo(() => {
    return [...gatingEvents].sort((a, b) => a.time_lag_minutes - b.time_lag_minutes);
  }, [gatingEvents]);

  // Group by mechanism
  const mechanismGroups = useMemo(() => {
    const groups: Record<string, GatingEvent[]> = {};
    gatingEvents.forEach(e => {
      const key = e.mechanism_hint;
      if (!groups[key]) groups[key] = [];
      groups[key].push(e);
    });
    return groups;
  }, [gatingEvents]);

  // Statistics
  const stats = useMemo(() => {
    if (gatingEvents.length === 0) return null;
    const lags = gatingEvents.map(e => e.time_lag_minutes);
    const primaryLeading = gatingEvents.filter(e => e.leading_ptm.toLowerCase() === primaryPtmType.toLowerCase()).length;
    const secondaryLeading = gatingEvents.filter(e => e.leading_ptm.toLowerCase() === secondaryPtmType.toLowerCase()).length;
    return {
      count: gatingEvents.length,
      minLag: Math.min(...lags),
      maxLag: Math.max(...lags),
      avgLag: lags.reduce((a, b) => a + b, 0) / lags.length,
      primaryLeading,
      secondaryLeading,
    };
  }, [gatingEvents, primaryPtmType, secondaryPtmType]);

  // Max time for timeline scaling
  const maxTime = useMemo(() => {
    if (gatingEvents.length === 0) return 60;
    return Math.max(...gatingEvents.map(e => e.time_lag_minutes), 10) * 1.2;
  }, [gatingEvents]);

  if (gatingEvents.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          Sequential Gating 이벤트가 감지되지 않았습니다.
        </CardContent>
      </Card>
    );
  }

  const getLeadingColor = (ptm: string) => {
    return ptm.toLowerCase() === primaryPtmType.toLowerCase()
      ? { bg: 'bg-blue-500', text: 'text-blue-700', light: 'bg-blue-100', border: 'border-blue-300' }
      : { bg: 'bg-amber-500', text: 'text-amber-700', light: 'bg-amber-100', border: 'border-amber-300' };
  };

  const getLaggingColor = (ptm: string) => {
    return ptm.toLowerCase() === primaryPtmType.toLowerCase()
      ? { bg: 'bg-blue-400', text: 'text-blue-600', light: 'bg-blue-50', border: 'border-blue-200' }
      : { bg: 'bg-amber-400', text: 'text-amber-600', light: 'bg-amber-50', border: 'border-amber-200' };
  };

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      {stats && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Sequential Gating Summary</CardTitle>
            <CardDescription>
              시간 지연(Time Lag) 기반 PTM 순차 활성화 패턴 분석
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 rounded-lg bg-muted/50 border text-center">
                <p className="text-2xl font-bold">{stats.count}</p>
                <p className="text-xs text-muted-foreground">Gating Events</p>
              </div>
              <div className="p-3 rounded-lg bg-muted/50 border text-center">
                <p className="text-2xl font-bold">{stats.avgLag.toFixed(1)}<span className="text-sm font-normal">min</span></p>
                <p className="text-xs text-muted-foreground">Avg Time Lag</p>
              </div>
              <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 text-center">
                <p className="text-2xl font-bold text-blue-700">{stats.primaryLeading}</p>
                <p className="text-xs text-blue-600">{pType} Leading</p>
              </div>
              <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-center">
                <p className="text-2xl font-bold text-amber-700">{stats.secondaryLeading}</p>
                <p className="text-xs text-amber-600">{sType} Leading</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Timeline Visualization */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Gating Timeline</CardTitle>
          <CardDescription>
            각 단백질의 Leading PTM → Lagging PTM 순차 활성화 타임라인
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {sortedEvents.map((event, idx) => {
              const leadColor = getLeadingColor(event.leading_ptm);
              const lagColor = getLaggingColor(event.lagging_ptm);
              const lagPercent = Math.min((event.time_lag_minutes / maxTime) * 100, 95);
              const isSelected = selectedEvent?.gene === event.gene;

              return (
                <div key={`${event.gene}-${idx}`}>
                  <div
                    className={`relative flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-all hover:bg-muted/50 ${
                      isSelected ? 'bg-muted/70 ring-1 ring-primary' : ''
                    }`}
                    onClick={() => setSelectedEvent(isSelected ? null : event)}
                  >
                    {/* Gene name */}
                    <div className="w-[80px] shrink-0">
                      <span className="font-mono font-semibold text-sm">{event.gene}</span>
                    </div>

                    {/* Timeline bar */}
                    <div className="flex-1 relative h-8">
                      {/* Background track */}
                      <div className="absolute inset-0 bg-gray-100 rounded-full" />

                      {/* Leading PTM marker (at 0) */}
                      <div
                        className={`absolute left-0 top-0 h-8 w-8 rounded-full ${leadColor.bg} flex items-center justify-center z-10`}
                        title={`${event.leading_ptm} @ ${event.leading_first_tp}`}
                      >
                        <span className="text-white text-[9px] font-bold">
                          {event.leading_ptm.charAt(0).toUpperCase()}
                        </span>
                      </div>

                      {/* Arrow / connection line */}
                      <div
                        className="absolute top-[14px] left-8 h-[4px] bg-gradient-to-r from-gray-300 to-gray-400 rounded"
                        style={{ width: `calc(${lagPercent}% - 32px)` }}
                      />

                      {/* Time lag label */}
                      <div
                        className="absolute top-0 text-[9px] text-muted-foreground font-mono"
                        style={{ left: `calc(${lagPercent / 2}% + 16px)`, transform: 'translateX(-50%)' }}
                      >
                        {event.time_lag_minutes.toFixed(1)}min
                      </div>

                      {/* Lagging PTM marker */}
                      <div
                        className={`absolute top-0 h-8 w-8 rounded-full ${lagColor.bg} flex items-center justify-center z-10`}
                        style={{ left: `${lagPercent}%` }}
                        title={`${event.lagging_ptm} @ ${event.lagging_first_tp}`}
                      >
                        <span className="text-white text-[9px] font-bold">
                          {event.lagging_ptm.charAt(0).toUpperCase()}
                        </span>
                      </div>
                    </div>

                    {/* Mechanism badge */}
                    <div className="w-[140px] shrink-0 text-right">
                      <Badge variant="outline" className="text-[9px] whitespace-nowrap">
                        {event.time_lag_minutes <= 5 ? 'Direct cascade' :
                         event.time_lag_minutes <= 15 ? 'Signal priming' :
                         event.time_lag_minutes <= 30 ? 'Conformational' : 'Transcriptional'}
                      </Badge>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {isSelected && (
                    <div className="ml-[92px] mr-[152px] p-3 bg-muted/30 rounded-lg border text-xs animate-in slide-in-from-top-1 duration-200 mb-1">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <p className="text-muted-foreground mb-0.5">Leading PTM</p>
                          <p className={`font-semibold ${leadColor.text}`}>
                            {event.leading_ptm.charAt(0).toUpperCase() + event.leading_ptm.slice(1)} @ {event.leading_first_tp}
                          </p>
                        </div>
                        <div>
                          <p className="text-muted-foreground mb-0.5">Lagging PTM</p>
                          <p className={`font-semibold ${lagColor.text}`}>
                            {event.lagging_ptm.charAt(0).toUpperCase() + event.lagging_ptm.slice(1)} @ {event.lagging_first_tp}
                          </p>
                        </div>
                      </div>
                      <div className="mt-2">
                        <p className="text-muted-foreground mb-0.5">Inferred Mechanism</p>
                        <p className="text-foreground">{event.mechanism_hint}</p>
                      </div>
                      <div className="mt-2">
                        <p className="text-muted-foreground mb-0.5">Time Lag</p>
                        <p className="font-mono font-semibold">{event.time_lag_minutes.toFixed(1)} minutes</p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Legend */}
          <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground flex-wrap border-t pt-3">
            <div className="flex items-center gap-1.5">
              <div className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center">
                <span className="text-white text-[8px] font-bold">P</span>
              </div>
              <span>{pType}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-5 h-5 rounded-full bg-amber-500 flex items-center justify-center">
                <span className="text-white text-[8px] font-bold">U</span>
              </div>
              <span>{sType}</span>
            </div>
            <span className="text-muted-foreground/60">|</span>
            <span>Circle = PTM first appearance, Line = time lag between leading and lagging PTM</span>
          </div>
        </CardContent>
      </Card>

      {/* Mechanism Groups */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Mechanism Classification</CardTitle>
          <CardDescription>
            Time Lag 기반 추론된 메커니즘별 분류
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {Object.entries(mechanismGroups).map(([mechanism, events]) => (
              <div key={mechanism} className="p-3 rounded-lg border bg-muted/20">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-sm">{mechanism}</h4>
                  <Badge variant="secondary" className="text-xs">{events.length} events</Badge>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {events.map((e, i) => {
                    const leadColor = getLeadingColor(e.leading_ptm);
                    return (
                      <Badge
                        key={`${e.gene}-${i}`}
                        variant="outline"
                        className={`text-xs ${leadColor.border} ${leadColor.light}`}
                      >
                        {e.gene} ({e.time_lag_minutes.toFixed(1)}min)
                      </Badge>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
