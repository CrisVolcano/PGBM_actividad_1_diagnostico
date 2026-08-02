// ============================================================
// PGBM - Actividad 4.12
// App GEE: comparador sincronizado de modelos de clasificacion 20 m
//
// Assets esperados:
// - 5 imagenes multibanda, una por region/cuadrante
// - Bandas por imagen:
//   b1 = svm
//   b2 = rf
//   b3 = dnn
//   b4 = xgboost
// ============================================================


// ============================================================
// 0. CONFIGURACION
// ============================================================

var REGION_ASSETS = {
  '1': 'projects/ee-andresaguilarba20pca/assets/class20m_region1_models',
  '2': 'projects/ee-andresaguilarba20pca/assets/class20m_region_2_models',
  '3': 'projects/ee-andresaguilarba20pca/assets/class20m_region_3_models',
  '4': 'projects/ee-andresaguilarba20pca/assets/class20m_region_4_models',
  '5': 'projects/ee-andresaguilarba20pca/assets/class20m_region_5_models'
};

var REGION_VIEWS = {
  '1': {lon: -85.504164, lat: 10.323108, zoom: 10},
  '2': {lon: -82.188008, lat: 8.417028, zoom: 10},
  '3': {lon: -87.784864, lat: 15.305606, zoom: 10},
  '4': {lon: -89.235861, lat: 13.687567, zoom: 10},
  '5': {lon: -86.747853, lat: 14.333453, zoom: 10}
};

var BAND_NAMES = ['svm', 'rf', 'dnn', 'xgboost'];

var MODELS = [
  {key: 'svm', title: 'SVM'},
  {key: 'rf', title: 'Random Forest'},
  {key: 'dnn', title: 'DNN'},
  {key: 'xgboost', title: 'XGBoost'}
];

var CLASS_VALUES = [11, 12, 13, 14, 15, 21, 22, 23, 24, 25];
var CLASS_INDEXES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

var CLASSES = [
  {value: 11, label: 'bosques latifoliados y mixtos', color: '#006D2C'},
  {value: 12, label: 'bosques de coniferas', color: '#1F6F78'},
  {value: 13, label: 'bosques de mangle', color: '#00A6A6'},
  {value: 14, label: 'bosques secos', color: '#A6A63A'},
  {value: 15, label: 'plantaciones forestales', color: '#7CB342'},
  {value: 21, label: 'cultivos arboreos', color: '#C58B20'},
  {value: 22, label: 'zonas agricolas no arboreas', color: '#F2D16B'},
  {value: 23, label: 'construido', color: '#D73027'},
  {value: 24, label: 'cuerpos de agua', color: '#2C7FB8'},
  {value: 25, label: 'otras tierras', color: '#BDBDBD'}
];

var CLASS_PALETTE = CLASSES.map(function(item) {
  return item.color;
});

var CLASS_LOOKUP = {};
CLASSES.forEach(function(item) {
  CLASS_LOOKUP[item.value] = item;
});

var CLASS_VIS = {
  min: 1,
  max: 10,
  palette: CLASS_PALETTE
};

var DEFAULT_REGION = '1';
var DEFAULT_OPACITY = 0.86;
var DEFAULT_BASEMAP = 'SATELLITE';
var DISPLAY_SCALE = 20;
var FORCE_NATIVE_PROJECTION = true;


// ============================================================
// 1. ESTADO DE LA APP
// ============================================================

var currentRegion = DEFAULT_REGION;
var currentImage = null;
var selectedPoint = null;
var currentOpacity = DEFAULT_OPACITY;


// ============================================================
// 2. ESTILOS UI
// ============================================================

var panelStyle = {
  width: '345px',
  padding: '14px',
  stretch: 'vertical',
  backgroundColor: '#F8FAFC'
};

var titleStyle = {
  fontSize: '20px',
  fontWeight: 'bold',
  color: '#111827',
  margin: '0 0 4px 0'
};

var subtitleStyle = {
  fontSize: '12px',
  color: '#475569',
  margin: '0 0 14px 0'
};

var sectionTitleStyle = {
  fontSize: '13px',
  fontWeight: 'bold',
  color: '#111827',
  margin: '14px 0 8px 0'
};

var smallTextStyle = {
  fontSize: '11px',
  color: '#475569',
  margin: '4px 0'
};

var mapTitleStyle = {
  position: 'top-left',
  padding: '7px 10px',
  margin: '8px',
  color: '#FFFFFF',
  backgroundColor: 'rgba(15, 23, 42, 0.82)',
  fontWeight: 'bold',
  fontSize: '13px'
};


// ============================================================
// 3. FUNCIONES DE DATOS Y VISUALIZACION
// ============================================================

function getRegionImage(regionKey) {
  return ee.Image(REGION_ASSETS[regionKey]).rename(BAND_NAMES).toByte();
}

function getCategoricalImage(image, modelKey) {
  var band = image.select(modelKey);
  var indexed = band.unmask(0).remap(CLASS_VALUES, CLASS_INDEXES, 0);
  var categorical = indexed.updateMask(indexed.neq(0)).rename(modelKey + '_class_index');

  if (FORCE_NATIVE_PROJECTION) {
    categorical = categorical.reproject({
      crs: band.projection(),
      scale: DISPLAY_SCALE
    });
  }

  return categorical;
}

function getClassLabel(value) {
  if (value === null || value === undefined || value === 0) {
    return 'Sin dato';
  }
  var info = CLASS_LOOKUP[String(value)];
  if (!info) {
    return String(value) + ' - clase no registrada';
  }
  return String(value) + ' - ' + info.label;
}

function makePointLayer() {
  var pointStyle = {
    color: 'FFFFFF',
    fillColor: 'FF2D2D',
    pointSize: 6,
    width: 2
  };

  var pointFc = ee.FeatureCollection([ee.Feature(selectedPoint)]);
  return ui.Map.Layer(
    pointFc.style(pointStyle),
    {},
    'Punto seleccionado',
    true,
    1
  );
}


// ============================================================
// 4. MAPAS
// ============================================================

function makeMap(model) {
  var map = ui.Map();
  map.setOptions(DEFAULT_BASEMAP);
  map.setControlVisibility(false, false, true, true, false, false, false);
  map.style().set('stretch', 'both');
  map.add(ui.Label(model.title, mapTitleStyle));
  map.onClick(handleMapClick);
  return map;
}

var mapByModel = {
  svm: makeMap(MODELS[0]),
  rf: makeMap(MODELS[1]),
  dnn: makeMap(MODELS[2]),
  xgboost: makeMap(MODELS[3])
};

var linkedMaps = ui.Map.Linker([
  mapByModel.svm,
  mapByModel.rf,
  mapByModel.dnn,
  mapByModel.xgboost
], 'change-bounds');

function refreshMapLayers() {
  if (!currentImage) {
    return;
  }

  MODELS.forEach(function(model) {
    var classImage = getCategoricalImage(currentImage, model.key);
    var modelLayer = ui.Map.Layer(
      classImage,
      CLASS_VIS,
      model.title + ' - region ' + currentRegion,
      true,
      currentOpacity
    );

    var layers = [modelLayer];
    if (selectedPoint !== null) {
      layers.push(makePointLayer());
    }
    mapByModel[model.key].layers().reset(layers);
  });
}

function centerCurrentRegion() {
  var view = REGION_VIEWS[currentRegion];
  mapByModel.svm.setCenter(view.lon, view.lat, view.zoom);
}

function loadRegion(regionKey) {
  currentRegion = regionKey;
  currentImage = getRegionImage(regionKey);
  selectedPoint = null;

  refreshMapLayers();
  centerCurrentRegion();
  updateInspectorEmpty();
  statusLabel.setValue('Region ' + regionKey + ' cargada');
}

function setBasemap(mapType) {
  Object.keys(mapByModel).forEach(function(key) {
    mapByModel[key].setOptions(mapType);
  });
}


// ============================================================
// 5. INSPECCION POR CLIC
// ============================================================

var inspectorPanel = ui.Panel({
  style: {
    padding: '9px',
    backgroundColor: '#FFFFFF',
    border: '1px solid #E5E7EB'
  }
});

function updateInspectorEmpty() {
  inspectorPanel.clear();
  inspectorPanel.add(ui.Label('Consulta por clic', {
    fontWeight: 'bold',
    fontSize: '12px',
    color: '#111827',
    margin: '0 0 6px 0'
  }));
  inspectorPanel.add(ui.Label(
    'Haz clic sobre cualquier panel para leer la clase predicha por los cuatro modelos.',
    smallTextStyle
  ));
}

function addInspectorRow(modelTitle, value) {
  inspectorPanel.add(ui.Label(modelTitle + ': ' + getClassLabel(value), {
    fontSize: '11px',
    color: '#111827',
    margin: '2px 0'
  }));
}

function handleMapClick(coords) {
  if (!currentImage) {
    return;
  }

  selectedPoint = ee.Geometry.Point([coords.lon, coords.lat]);
  refreshMapLayers();

  inspectorPanel.clear();
  inspectorPanel.add(ui.Label('Consultando pixel...', {
    fontWeight: 'bold',
    fontSize: '12px',
    color: '#111827',
    margin: '0 0 6px 0'
  }));

  var clickedRegion = currentRegion;
  var values = currentImage.reduceRegion({
    reducer: ee.Reducer.first(),
    geometry: selectedPoint,
    scale: 20,
    bestEffort: true,
    maxPixels: 1e8
  });

  values.evaluate(function(result) {
    if (clickedRegion !== currentRegion) {
      return;
    }

    inspectorPanel.clear();
    inspectorPanel.add(ui.Label('Valores del pixel', {
      fontWeight: 'bold',
      fontSize: '12px',
      color: '#111827',
      margin: '0 0 6px 0'
    }));
    inspectorPanel.add(ui.Label(
      coords.lon.toFixed(5) + ', ' + coords.lat.toFixed(5),
      smallTextStyle
    ));

    if (!result) {
      inspectorPanel.add(ui.Label('Sin dato en este punto.', smallTextStyle));
      return;
    }

    addInspectorRow('SVM', result.svm);
    addInspectorRow('Random Forest', result.rf);
    addInspectorRow('DNN', result.dnn);
    addInspectorRow('XGBoost', result.xgboost);
  });
}


// ============================================================
// 6. PANEL DERECHO
// ============================================================

function makeLegendRow(item) {
  var colorBox = ui.Label('', {
    backgroundColor: item.color,
    padding: '8px',
    margin: '0 8px 4px 0',
    border: '1px solid #CBD5E1'
  });

  var label = ui.Label(item.value + ' - ' + item.label, {
    fontSize: '11px',
    color: '#111827',
    margin: '0 0 4px 0'
  });

  return ui.Panel({
    widgets: [colorBox, label],
    layout: ui.Panel.Layout.flow('horizontal'),
    style: {margin: '0'}
  });
}

function makeLegendPanel() {
  var legend = ui.Panel({
    style: {
      padding: '8px',
      backgroundColor: '#FFFFFF',
      border: '1px solid #E5E7EB'
    }
  });

  CLASSES.forEach(function(item) {
    legend.add(makeLegendRow(item));
  });

  return legend;
}

var regionSelect = ui.Select({
  items: ['1', '2', '3', '4', '5'],
  value: DEFAULT_REGION,
  onChange: loadRegion,
  style: {stretch: 'horizontal'}
});

var opacitySlider = ui.Slider({
  min: 0,
  max: 1,
  value: DEFAULT_OPACITY,
  step: 0.02,
  onChange: function(value) {
    currentOpacity = value;
    refreshMapLayers();
  },
  style: {stretch: 'horizontal'}
});

var basemapSelect = ui.Select({
  items: ['SATELLITE', 'HYBRID', 'ROADMAP', 'TERRAIN'],
  value: DEFAULT_BASEMAP,
  onChange: setBasemap,
  style: {stretch: 'horizontal'}
});

var recenterButton = ui.Button({
  label: 'Centrar zona actual',
  onClick: centerCurrentRegion,
  style: {stretch: 'horizontal'}
});

var statusLabel = ui.Label('', {
  fontSize: '11px',
  color: '#2563EB',
  margin: '8px 0 0 0'
});

var sidebar = ui.Panel({
  style: panelStyle,
  widgets: [
    ui.Label('Comparador 20 m', titleStyle),
    ui.Label('Clasificacion por modelo en cuatro paneles sincronizados.', subtitleStyle),

    ui.Label('Zona / cuadrante', sectionTitleStyle),
    regionSelect,
    recenterButton,

    ui.Label('Visualizacion', sectionTitleStyle),
    ui.Label('Opacidad de clasificacion', smallTextStyle),
    opacitySlider,
    ui.Label('Mapa base', smallTextStyle),
    basemapSelect,

    ui.Label('Leyenda', sectionTitleStyle),
    makeLegendPanel(),

    ui.Label('Inspeccion', sectionTitleStyle),
    inspectorPanel,
    statusLabel
  ]
});


// ============================================================
// 7. LAYOUT FINAL
// ============================================================

var topRow = ui.Panel({
  widgets: [mapByModel.svm, mapByModel.rf],
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'both'}
});

var bottomRow = ui.Panel({
  widgets: [mapByModel.dnn, mapByModel.xgboost],
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'both'}
});

var mapGrid = ui.Panel({
  widgets: [topRow, bottomRow],
  layout: ui.Panel.Layout.flow('vertical'),
  style: {stretch: 'both'}
});

var app = ui.Panel({
  widgets: [mapGrid, sidebar],
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'both'}
});

ui.root.clear();
ui.root.add(app);

updateInspectorEmpty();
loadRegion(DEFAULT_REGION);
