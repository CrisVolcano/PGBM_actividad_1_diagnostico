// ============================================================
// PGBM - Actividad 1.6
// Extracción espectro-temporal Sentinel-2 SR mensual a 20 m
// Para batches seleccionados manualmente desde tablas importadas
//
// Máscara: s2cloudless + sombras + SCL
// Salida: CSV mensual por batch en Google Drive
//
// NOTA DE TRAZABILIDAD:
// Este script documenta la lógica usada para la extracción ya ejecutada
// en Google Earth Engine. No debe modificarse retroactivamente para
// reinterpretar los CSV ya exportados.
// ============================================================


// ============================================================
// 0. CONFIGURACIÓN GENERAL
// ============================================================

// IMPORTANTE:
// En GEE debes importar el asset como tabla.
// Normalmente GEE crea una variable llamada "table" arriba del script.
//
// Ejemplo automático de GEE:
// var table = ee.FeatureCollection("projects/ee-jesusc461/assets/pgbm_s2sr_batches/s2sr_units_Panam_2021_batch_001");
//
// Este código usa esa variable importada.

var DRIVE_FOLDER = 'PGBM_S2SR_monthly_s2cloudless';

// Parámetros de extracción
var scale = 20;

// Parámetros s2cloudless
var CLD_PRB_THRESH = 50;  // probar 40, 50, 60
var NIR_DRK_THRESH = 0.15;
var CLD_PRJ_DIST = 1;    // km
var BUFFER = 60;         // m

// No necesitamos geometría en el CSV final porque exportamos lon_out/lat_out.
var EXPORT_GEOMETRIES = false;


// ============================================================
// 1. LISTA MANUAL DE TABLAS IMPORTADAS A EXPORTAR
// ============================================================
//
// run: true  = crea export
// run: false = omite export
//
// tableObj debe ser la variable importada en GEE.
// Si solo importaste una tabla, deja tableObj: table.
//

var BATCHES_TO_EXPORT = [
  {
    name: 's2sr_units_Guatemala_2020_batch_002',
    tableObj: table,
    run: true
  }
];

var batchesToRun = BATCHES_TO_EXPORT
  .filter(function(d) {
    return d.run === true;
  });

print('Total batch tables a procesar:', batchesToRun.length);
print('Batches seleccionados:', batchesToRun.map(function(d) { return d.name; }));


// ============================================================
// 2. FUNCIONES AUXILIARES CLIENT-SIDE
// ============================================================

function cleanName(name) {
  return name
    .replace(/[^A-Za-z0-9_]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .substring(0, 90);
}


// ============================================================
// 3. FUNCIONES SENTINEL-2 / S2CLOUDLESS
// ============================================================

function addCloudBands(img) {
  var cloudProb = ee.Image(img.get('s2cloudless')).select('probability');
  var isCloud = cloudProb.gt(CLD_PRB_THRESH).rename('clouds');

  return img.addBands([
    cloudProb.rename('cloud_prob'),
    isCloud
  ]);
}


function addShadowBands(img) {
  var scl = img.select('SCL');

  var notWater = scl.neq(6);

  var darkPixels = img.select('B8')
    .lt(NIR_DRK_THRESH * 10000)
    .multiply(notWater)
    .rename('dark_pixels');

  var shadowAzimuth = ee.Number(90)
    .subtract(ee.Number(img.get('MEAN_SOLAR_AZIMUTH_ANGLE')));

  var cloudProjection = img.select('clouds')
    .directionalDistanceTransform(shadowAzimuth, CLD_PRJ_DIST * 10)
    .reproject({
      crs: img.select(0).projection(),
      scale: 100
    })
    .select('distance')
    .mask()
    .rename('cloud_transform');

  var shadows = cloudProjection
    .multiply(darkPixels)
    .rename('shadows');

  return img.addBands([
    darkPixels,
    cloudProjection,
    shadows
  ]);
}


function addCloudShadowMask(img) {
  img = addCloudBands(img);
  img = addShadowBands(img);

  var isCloudOrShadow = img.select('clouds')
    .add(img.select('shadows'))
    .gt(0);

  var cloudShadowMask = isCloudOrShadow
    .focalMin(2)
    .focalMax(BUFFER / 20)
    .reproject({
      crs: img.select(0).projection(),
      scale: 20
    })
    .rename('cloud_shadow_mask');

  return img.addBands(cloudShadowMask);
}


function applyMask(img) {
  var scl = img.select('SCL');

  var sclMask = scl.neq(0)    // no data
    .and(scl.neq(1))          // saturated / defective
    .and(scl.neq(3))          // cloud shadow
    .and(scl.neq(8))          // cloud medium probability
    .and(scl.neq(9))          // cloud high probability
    .and(scl.neq(10))         // cirrus
    .and(scl.neq(11));        // snow / ice

  var cloudShadowMask = img.select('cloud_shadow_mask').eq(0);

  return img
    .updateMask(sclMask)
    .updateMask(cloudShadowMask);
}


function scaleS2(img) {
  var optical = img.select([
    'B2', 'B3', 'B4',
    'B5', 'B6', 'B7',
    'B8', 'B8A',
    'B11', 'B12'
  ]).multiply(0.0001);

  return img.addBands(optical, null, true);
}


function addIndices(img) {
  var b2 = img.select('B2');
  var b3 = img.select('B3');
  var b4 = img.select('B4');
  var b5 = img.select('B5');
  var b7 = img.select('B7');
  var b8 = img.select('B8');
  var b8a = img.select('B8A');
  var b11 = img.select('B11');
  var b12 = img.select('B12');

  var ndvi = b8.subtract(b4)
    .divide(b8.add(b4))
    .rename('NDVI');

  var ndvi8a = b8a.subtract(b4)
    .divide(b8a.add(b4))
    .rename('NDVI8A');

  var ndre = b8a.subtract(b5)
    .divide(b8a.add(b5))
    .rename('NDRE');

  return img.addBands([
    ndvi,
    ndvi8a,
    ndre
  ]);
}


// ============================================================
// 4. BANDAS Y CAMPOS DE SALIDA
// ============================================================

var spectralBands = [
  'B2', 'B3', 'B4',
  'B5', 'B6', 'B7',
  'B8', 'B8A',
  'B11', 'B12',
  'NDVI', 'NDVI8A', 'NDRE'
];

var bandsForCollection = spectralBands.concat(['cloud_prob']);

var allOutputBands = spectralBands.concat([
  'n_obs_clean',
  'cloud_prob_median'
]);

var pointProperties = [
  'extract_id',
  'lon_out',
  'lat_out',
  'year_ref',
  'n_records_extract_unit',
  'xy_group_id',
  'tipo_grupo_xy',
  'n_registros',
  'n_paises',
  'n_fuentes',
  'n_anios',
  'n_nivel1',
  'n_nivel2',
  'anio_min',
  'anio_max',
  'pais_grupo',
  'country',
  'source',
  'level_1',
  'level_2',
  'n_unique_country_extract_unit',
  'n_unique_source_extract_unit',
  'n_unique_level1_extract_unit',
  'n_unique_level2_extract_unit',
  'batch_id'
];

var metadataProperties = [
  'month',
  'year_extraction',
  's2_collection',
  'cloud_mask_method',
  'cloud_prob_threshold',
  'nir_dark_threshold',
  'cloud_proj_dist_km',
  'buffer_m',
  'scale_m'
];

var exportSelectors = pointProperties
  .concat(metadataProperties)
  .concat(allOutputBands);


// ============================================================
// 5. IMAGEN VACÍA PARA MESES SIN DATOS
// ============================================================

function emptyMonthlyImage() {
  var emptySpectral = ee.Image.constant(
      ee.List.repeat(-9999, spectralBands.length)
    )
    .rename(spectralBands);

  var nObs = ee.Image.constant(0).rename('n_obs_clean');
  var cloudProb = ee.Image.constant(-9999).rename('cloud_prob_median');

  return emptySpectral
    .addBands(nObs)
    .addBands(cloudProb);
}


function monthlyComposite(monthly) {
  var hasData = monthly.size().gt(0);

  var withData = monthly.select(spectralBands)
    .median()
    .unmask(-9999)
    .addBands(
      monthly.count()
        .select('B4')
        .rename('n_obs_clean')
        .unmask(0)
    )
    .addBands(
      monthly.select('cloud_prob')
        .median()
        .rename('cloud_prob_median')
        .unmask(-9999)
    )
    .select(allOutputBands);

  var noData = emptyMonthlyImage()
    .select(allOutputBands);

  return ee.Image(
    ee.Algorithms.If(hasData, withData, noData)
  );
}


// ============================================================
// 6. PREPARAR PUNTOS
// ============================================================

function preparePoints(pointsRaw) {
  var points = ee.FeatureCollection(pointsRaw).map(function(f) {
    var coords = f.geometry().coordinates();
    var lon = ee.Number(coords.get(0));
    var lat = ee.Number(coords.get(1));

    var propNames = f.propertyNames();

    var extractId = ee.Algorithms.If(
      propNames.contains('extract_id'),
      f.get('extract_id'),
      f.get('\ufeffextract_id')
    );

    return f
      .set('extract_id', extractId)
      .set('lon_out', lon)
      .set('lat_out', lat);
  });

  return points;
}


// ============================================================
// 7. CONSTRUIR EXTRACCIÓN MENSUAL PARA UNA TABLA IMPORTADA
// ============================================================

function buildMonthlySamples(pointsRaw) {
  var points = preparePoints(pointsRaw);

  var year = ee.Number.parse(
    ee.Feature(points.first()).get('year_ref')
  );

  var start = ee.Date.fromYMD(year, 1, 1);
  var end = ee.Date.fromYMD(year.add(1), 1, 1);

  var region = points.geometry().bounds(1000);

  var s2Sr = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(region)
    .filterDate(start, end);

  var s2Clouds = ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY')
    .filterBounds(region)
    .filterDate(start, end);

  var joinedRaw = ee.ImageCollection(
    ee.Join.saveFirst('s2cloudless').apply({
      primary: s2Sr,
      secondary: s2Clouds,
      condition: ee.Filter.equals({
        leftField: 'system:index',
        rightField: 'system:index'
      })
    })
  );

  var joined = joinedRaw.filter(ee.Filter.notNull(['s2cloudless']));

  var s2Clean = joined
    .map(addCloudShadowMask)
    .map(applyMask)
    .map(scaleS2)
    .map(addIndices)
    .select(bandsForCollection);

  var months = ee.List.sequence(1, 12);

  var monthlySamples = ee.FeatureCollection(
    months.map(function(m) {
      m = ee.Number(m);

      var monthStart = ee.Date.fromYMD(year, m, 1);
      var monthEnd = monthStart.advance(1, 'month');

      var monthly = s2Clean.filterDate(monthStart, monthEnd);

      var composite = monthlyComposite(monthly)
        .set('year_ref', year)
        .set('month', m);

      var samples = composite.sampleRegions({
        collection: points,
        properties: pointProperties,
        scale: scale,
        geometries: EXPORT_GEOMETRIES,
        tileScale: 8
      });

      return samples.map(function(f) {
        return f
          .set('month', m)
          .set('year_extraction', year)
          .set('s2_collection', 'COPERNICUS/S2_SR_HARMONIZED')
          .set('cloud_mask_method', 's2cloudless_scl_shadow')
          .set('cloud_prob_threshold', CLD_PRB_THRESH)
          .set('nir_dark_threshold', NIR_DRK_THRESH)
          .set('cloud_proj_dist_km', CLD_PRJ_DIST)
          .set('buffer_m', BUFFER)
          .set('scale_m', scale);
      });
    })
  ).flatten();

  return monthlySamples;
}


// ============================================================
// 8. CREAR EXPORTS A DRIVE PARA LAS TABLAS IMPORTADAS MARCADAS
// ============================================================

batchesToRun.forEach(function(batch, i) {
  var cleanBatchName = cleanName(batch.name);

  var outputName = 'pgbm_s2sr_monthly_s2cloudless_' + cleanBatchName;

  print('Creando export', i + 1, 'de', batchesToRun.length, outputName);

  var monthlySamples = buildMonthlySamples(batch.tableObj);

  Export.table.toDrive({
    collection: monthlySamples,
    description: outputName,
    folder: DRIVE_FOLDER,
    fileNamePrefix: outputName,
    fileFormat: 'CSV',
    selectors: exportSelectors
  });
});
