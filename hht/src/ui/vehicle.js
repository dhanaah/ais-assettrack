// Vehicle picker: type to search, tap a chip to choose; a new number is kept on this HHT for next time. Developed by DT
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity } from 'react-native';
import { S, C } from './kit';
import { allVehicles, cleanVeh } from '../lib/vehicles';

export function VehiclePicker({ value, onChange, label = 'Vehicle number *' }) {
  const [list, setList] = useState([]); const [q, setQ] = useState(value || '');
  useEffect(() => { allVehicles().then(setList); }, []);
  useEffect(() => { setQ(value || ''); }, [value]);
  const f = cleanVeh(q); const shown = (f ? list.filter((v) => v.includes(f)) : list).slice(0, 12);
  return (<View>
    <Text style={S.mute}>{label}</Text>
    <TextInput style={[S.input, { fontSize: 18, fontWeight: '700', letterSpacing: 1 }]} value={q} onChangeText={(t) => { setQ(t.toUpperCase()); onChange(cleanVeh(t)); }} autoCapitalize="characters" autoCorrect={false} placeholder="TN09AB1234 - type or pick below" />
    {shown.length ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>{shown.map((v) => <TouchableOpacity key={v} onPress={() => { setQ(v); onChange(v); }} style={{ paddingHorizontal: 10, paddingVertical: 7, borderRadius: 10, borderWidth: 1, borderColor: v === cleanVeh(value) ? C.ok : C.accent, backgroundColor: v === cleanVeh(value) ? C.ok : 'transparent' }}><Text style={{ fontWeight: '700', color: v === cleanVeh(value) ? '#fff' : C.accent }}>{v}</Text></TouchableOpacity>)}</View>
      : f ? <Text style={[S.mute, { marginBottom: 8 }]}>New vehicle - it is kept on this HHT for next time.</Text> : <Text style={[S.mute, { marginBottom: 8 }]}>No vehicles yet - type the number, or add them in Setup › Vehicles.</Text>}
  </View>);
}
