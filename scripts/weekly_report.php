<?php 
ini_set('display_errors', 1);
ini_set('display_startup_errors', 1);
error_reporting(E_ALL);
require_once 'scripts/common.php';

$week_offset = isset($_GET['week_offset']) ? intval($_GET['week_offset']) : 0;
$startdate = strtotime('last sunday') - (7*86400) + ($week_offset * 7 * 86400);
$enddate = strtotime('last sunday') - (1*86400) + ($week_offset * 7 * 86400);

$debug = false;

function safe_percentage($count, $prior_count) {
	if ($prior_count !== 0) {
		$percentagediff = round((($count - $prior_count) / $prior_count) * 100);
	} else {
		if ($count > 0) {
			$percentagediff = INF;
		} else {
			$percentagediff = 0;
		}
	}
	return $percentagediff;
}

$db = new SQLite3('./scripts/birds.db', SQLITE3_OPEN_READONLY);
$db->busyTimeout(1000);

$statement1 = $db->prepare('SELECT Sci_Name, Com_Name, COUNT(*) FROM detections WHERE Date BETWEEN "' . date("Y-m-d", $startdate) . '" AND "' . date("Y-m-d", $enddate) . '" GROUP By Sci_Name ORDER BY COUNT(*) DESC');
ensure_db_ok($statement1);
$result1 = $statement1->execute();
$detections = [];
while ($detection = $result1->fetchArray(SQLITE3_ASSOC)) {
  $com_name = $detection["Com_Name"];
  $sci_name = $detection["Sci_Name"];
  $scount = $detection["COUNT(*)"];

  # previous week
  $statement2 = $db->prepare('SELECT COUNT(*) FROM detections WHERE Sci_Name = :sci_name AND Date BETWEEN :prev_startdate AND :prev_enddate');
  ensure_db_ok($statement2);
  $statement2->bindValue(':sci_name', $detection["Sci_Name"], SQLITE3_TEXT);
  $statement2->bindValue(':prev_startdate', date("Y-m-d", $startdate - (7 * 86400)), SQLITE3_TEXT);
  $statement2->bindValue(':prev_enddate', date("Y-m-d", $enddate - (7 * 86400)), SQLITE3_TEXT);
  $result2 = $statement2->execute();
  $priorweekcount = $result2->fetchArray(SQLITE3_ASSOC)['COUNT(*)'];
  $percentagediff = safe_percentage($scount, $priorweekcount);

  # is_first_seen?
  $statement3 = $db->prepare('SELECT COUNT(*) FROM detections WHERE Sci_Name = :sci_name AND Date NOT BETWEEN :startdate AND :enddate');
  ensure_db_ok($statement3);
  $statement3->bindValue(':sci_name', $sci_name, SQLITE3_TEXT);
  $statement3->bindValue(':startdate', date("Y-m-d", $startdate), SQLITE3_TEXT);
  $statement3->bindValue(':enddate', date("Y-m-d", $enddate), SQLITE3_TEXT);
  $result3 = $statement3->execute();
  $totalcount = $result3->fetchArray(SQLITE3_ASSOC)['COUNT(*)'];
  $is_first_seen = $totalcount === 0;

  $detections[$com_name] = ["count" => $scount, "percentagediff" => $percentagediff, "is_first_seen" => $is_first_seen];
}

$statement4 = $db->prepare('SELECT COUNT(*) FROM detections WHERE Date BETWEEN "'.date("Y-m-d",$startdate).'" AND "'.date("Y-m-d",$enddate).'"');
ensure_db_ok($statement4);
$result4 = $statement4->execute();
$totalcount = $result4->fetchArray(SQLITE3_ASSOC)['COUNT(*)'];

$statement5 = $db->prepare('SELECT COUNT(*) FROM detections WHERE Date BETWEEN "'.date("Y-m-d",$startdate- (7*86400)).'" AND "'.date("Y-m-d",$enddate- (7*86400)).'"');
ensure_db_ok($statement5);
$result5 = $statement5->execute();
$priortotalcount = $result5->fetchArray(SQLITE3_ASSOC)['COUNT(*)'];

$statement6 = $db->prepare('SELECT COUNT(DISTINCT(Sci_Name)) FROM detections WHERE Date BETWEEN "'.date("Y-m-d",$startdate).'" AND "'.date("Y-m-d",$enddate).'"');
ensure_db_ok($statement6);
$result6 = $statement6->execute();
$totalspeciestally = $result6->fetchArray(SQLITE3_ASSOC)['COUNT(DISTINCT(Sci_Name))'];

$statement7 = $db->prepare('SELECT COUNT(DISTINCT(Sci_Name)) FROM detections WHERE Date BETWEEN "'.date("Y-m-d",$startdate- (7*86400)).'" AND "'.date("Y-m-d",$enddate- (7*86400)).'"');
ensure_db_ok($statement7);
$result7= $statement7->execute();
$priortotalspeciestally = $result7->fetchArray(SQLITE3_ASSOC)['COUNT(DISTINCT(Sci_Name))'];

$percentagedifftotal = safe_percentage($totalcount, $priortotalcount);

if(isset($_GET['ascii'])) {
	if($percentagedifftotal > 0) {
		$percentagedifftotal = "<span style='color:green;font-size:small'>+".$percentagedifftotal."%</span>";
	} else {
		$percentagedifftotal = "<span style='color:red;font-size:small'>-".abs($percentagedifftotal)."%</span>";
	}

	$percentagedifftotaldistinctspecies = safe_percentage($totalspeciestally, $priortotalspeciestally);
	if($percentagedifftotaldistinctspecies > 0) {
		$percentagedifftotaldistinctspecies = "<span style='color:green;font-size:small'>+".$percentagedifftotaldistinctspecies."%</span>";
	} else {
		$percentagedifftotaldistinctspecies = "<span style='color:red;font-size:small'>-".abs($percentagedifftotaldistinctspecies)."%</span>";
	}

	echo "# BirdNET-Pi: Week ".date('W', $enddate)." Report\n";

	echo "Total Detections: <b>".(int)$totalcount."</b> (".$percentagedifftotal.")<br>";
	echo "Unique Species Detected: <b>".(int)$totalspeciestally."</b> (".$percentagedifftotaldistinctspecies.")<br><br>";

	echo "= <b>Top 10 Species</b> =<br>";

	$i = 0;
	foreach($detections as $com_name=>$stats)
	{
    $count = $stats["count"];
    $percentagediff = $stats["percentagediff"];
		$i++;
		if($i <= 10) {
      if($percentagediff > 0) {
              $percentagediff = "<span style='color:green;font-size:small'>+".$percentagediff."%</span>";
      } else {
              $percentagediff = "<span style='color:red;font-size:small'>-".abs($percentagediff)."%</span>";
      }

      echo htmlspecialchars($com_name, ENT_QUOTES, 'UTF-8')." - ".$count." (".$percentagediff.")<br>";
		}
	}

	echo "<br>= <b>Species Detected for the First Time</b> =<br>";

  $newspeciescount=0;
	foreach($detections as $com_name=>$stats)
	{
		if($stats["is_first_seen"]) {
			$newspeciescount++;
			echo htmlspecialchars($com_name, ENT_QUOTES, 'UTF-8')." - ".intval($scount)."<br>";
		}
	}
	if($newspeciescount == 0) {
		echo "No new species were seen this week.";
	}

  $prevweek = date('W', $enddate) - 1;
  if($prevweek < 1) { $prevweek = 52; }

	echo "<hr><span style='font-size:small'>* data from ".date('Y-m-d', $startdate)." — ".date('Y-m-d',$enddate).".</span><br>";
	echo "<span style='font-size:small'>* percentages are calculated relative to week ".($prevweek).".</span>";

	die();
}

?>
<div class="brbanner"> <?php
echo "<h1>Week ".date('W', $enddate)." Report</h1>".date('F jS, Y',$startdate)." — ".date('F jS, Y',$enddate)."<br>";
?>
</div>
<br>
<?php // TODO: fix the box shadows, maybe make them a bit smaller on the tr ?>
<table align="center" style="box-shadow:unset"><tr><td style="background-color:transparent">
	<table>
	<thead>
		<tr>
			<th><?php echo "Top 10 Species: <br>"; ?></th>
		</tr>
	</thead>
	<tbody>
	<?php

	$i = 0;
	foreach($detections as $com_name=>$stats)
	{
		$i++;
		if($i <= 10) {
        $count = $stats["count"];
        $percentagediff = $stats["percentagediff"];
			if($percentagediff > 0) {
				$percentagediff = "<span style='color:green;font-size:small'>+".$percentagediff."%</span>";
			} else {
				$percentagediff = "<span style='color:red;font-size:small'>-".abs($percentagediff)."%</span>";
			}

			echo "<tr><td>".htmlspecialchars($com_name, ENT_QUOTES, 'UTF-8')."<br><small style=\"font-size:small\">".$count." (".$percentagediff.")</small><br></td></tr>";
		}
	}
	?>
	</tbody>
	</table>
	</td><td style="background-color:transparent">

	<table >
	<thead>
		<tr>
			<th><?php echo "Species Detected for the First Time: <br>"; ?></th>
		</tr>
	</thead>
	<tbody>
	<?php 

  $newspeciescount=0;
	foreach($detections as $com_name=>$stats)
	{
		if($stats["is_first_seen"]) {
			$newspeciescount++;
			echo "<tr><td>".htmlspecialchars($com_name, ENT_QUOTES, 'UTF-8')."<br><small style=\"font-size:small\">".intval($scount)."</small><br></td></tr>";
		}
	}
	if($newspeciescount == 0) {
		echo "<tr><td>No new species were seen this week.</td></tr>";
	}
	?>
	</tbody>
	</table>
	</td></tr></table>


<br>
<div style="text-align:center">
	<hr><small style="font-size:small">* percentages are calculated relative to week <?php echo date('W', $enddate) - 1; ?></small>
</div>
<div style="display:flex;justify-content:center;align-items:center;gap:12px;margin:12px auto 16px auto;">
  <a href="views.php?view=Weekly+Report&week_offset=<?php echo $week_offset - 1; ?>" style="font-size:1.3em;padding:4px 10px;background-color:rgb(219,255,235);border-radius:4px;box-shadow:0px 3px 1px -2px rgba(0,0,0,0.20),0px 2px 2px 0px rgba(0,0,0,0.14),0px 1px 5px 0px rgba(0,0,0,0.12);text-decoration:none;color:black;" title="Previous week">&#9664;</a>
  <span style="font-size:1.1em;font-weight:bold;">Week <?php echo date('W', $enddate); ?> (<?php echo date('M j', $startdate); ?> &ndash; <?php echo date('M j', $enddate); ?>)</span>
  <?php if ($week_offset < 0): ?>
  <a href="views.php?view=Weekly+Report&week_offset=<?php echo $week_offset + 1; ?>" style="font-size:1.3em;padding:4px 10px;background-color:rgb(219,255,235);border-radius:4px;box-shadow:0px 3px 1px -2px rgba(0,0,0,0.20),0px 2px 2px 0px rgba(0,0,0,0.14),0px 1px 5px 0px rgba(0,0,0,0.12);text-decoration:none;color:black;" title="Next week">&#9654;</a>
  <?php else: ?>
  <span style="font-size:1.3em;padding:4px 10px;opacity:0.3;cursor:not-allowed;">&#9654;</span>
  <?php endif; ?>
</div>
